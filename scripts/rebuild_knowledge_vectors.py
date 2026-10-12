#!/usr/bin/env python
"""Phase 5 §4.5：把某个知识库按**当前分块参数**重建为新一代索引（可灰度、可回滚）。

它解决什么问题
--------------

分块参数（``chunk_size`` / ``chunk_overlap``）变更后，**存量分块仍是旧参数的产物**：
旧块被静默截断、重叠从未生效。重新上传能修好单篇，但生产库不能靠「删了再传」——
文档 id 会变、审计链会断、期间检索不可用。本脚本对已有文档就地重跑解析与分块，
把新一代索引写到**另一个集合**，校验通过后再切读。

安全设计（对齐 ``backfill_hybrid_collection.py``）
--------------------------------------------------

* **缺省只读**：不带 ``--execute`` 时只打印计划（文档数 / 预计块数 / 预计耗时 /
  目标集合名 / 目标是否已存在），不写 MySQL、不写 Qdrant；
* **目标已存在则拒绝**（除非显式 ``--recreate``）：避免把半成品集合当成成品续写，
  那种续写不会报错，只会产出一个「点数少一半」的集合；
* **``--limit-docs``**：先用 1 篇验证链路，再全量；
* **灰度指针**（``knowledge_bases.active_collection``）：``--cutover`` 只翻转指针，
  旧集合与旧代次分块行都保留 → ``--rollback`` 立即生效，无需重算；
* **旧代次行不随 cutover 回收**：它们是回滚窗口的实体。回收是破坏性操作，
  必须由 ``--gc-old-epochs`` 显式触发，且脚本会先打印将删除的行数。

代次与 id
---------

新行的 ``chunk_epoch`` = ``config.chunk_epoch``（如 ``448-64-p1``：尺寸-重叠-策略版本），
``vector_id`` = :func:`app.services.knowledge_processor.vector_id_for`（带代次后缀）。
代次后缀不是装饰：``knowledge_chunks.vector_id`` 上有唯一索引，两代共存时若 id 只由
``(doc_id, index)`` 决定，新一代插入必然 ``IntegrityError``。

``doc.active_chunk_epoch`` 在**重建期**就翻到新代次，而不是等到 cutover：它是
「这份文档现在有哪一代分块」的事实陈述，分块列表与库级计数都依据它。检索侧不受
影响——``get_by_vector_id`` / ``list_by_vector_ids`` 刻意不带代次过滤，因此切读前
（指针仍指向旧集合）命中的旧 id 依然能查到内容，回滚同理。
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import List, Optional, Sequence

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import and_, func  # noqa: E402

from app.core.config import config  # noqa: E402
from app.core.database import sessionLocal  # noqa: E402
from app.core.vector_db import (  # noqa: E402
    collection_exists,
    create_hybrid_collection,
    get_qdrant_client,
    get_vector_size_for_model,
    hybrid_point_vector,
)
from app.models.knowledge_base import KnowledgeBase  # noqa: E402
from app.models.knowledge_chunk import KnowledgeChunk  # noqa: E402
from app.models.knowledge_document import KnowledgeDocument  # noqa: E402
from app.repositories.knowledge import KnowledgeChunkRepository  # noqa: E402
from app.services.knowledge_processor import vector_id_for  # noqa: E402
from app.utils.document import (  # noqa: E402
    DocumentParser,
    TextSplitter,
    chunk_type_for,
)
from app.utils.embedding import get_embedding_client  # noqa: E402
from app.utils.sparse import default_encoder  # noqa: E402

EMBED_BATCH = 32
UPSERT_BATCH = 256
#: 本机实测嵌入吞吐（块/秒，容器 CPU）。仅用于干跑时的耗时估算——
#: 宁可给出一个粗糙的量级，也不要让运维在毫无预期的情况下启动一个 8 小时的任务。
EMBED_CHUNKS_PER_SECOND = 1.4


def target_collection_name(kb_id: str, override: Optional[str] = None) -> str:
    """目标集合名：``kb_{kb_id}_v2``

    刻意**不复用** ``kb_{kb_id}``：新旧两代必须同时可查，回滚才有实体可回。
    加 ``_v2`` 而非时间戳，是为了让重跑（``--recreate``）落在同一个名字上，
    避免每次尝试都留下一个集合。
    """
    return override or f"kb_{kb_id}_v2"


def live_documents(session, kb_id: str, limit: Optional[int] = None) -> List[KnowledgeDocument]:
    """知识库下**存活**文档，按创建时间升序（重建顺序稳定可复现）"""
    query = (
        session.query(KnowledgeDocument)
        .filter(
            and_(
                KnowledgeDocument.kb_id == kb_id,
                KnowledgeDocument.deleted_at.is_(None),
            )
        )
        .order_by(KnowledgeDocument.created_at.asc())
    )
    if limit is not None:
        query = query.limit(limit)
    return query.all()


def chunk_document(doc: KnowledgeDocument) -> list:
    """解析 + 分块（只读；干跑与实际执行共用同一条路径）

    Raises:
        FileNotFoundError: 落盘原件缺失。**不跳过**——「原件丢了」必须显式暴露，
            静默跳过会让一篇文档在重建后凭空少掉分块，而没有任何报错。
    """
    path = Path(doc.file_url or "")
    if not path.is_file():
        raise FileNotFoundError(f"文档原件缺失: {doc.id} -> {path}")
    segments = DocumentParser.parse_segments(str(path), doc.file_type)
    return TextSplitter().split_segments(segments)


def existing_epoch_chunk_count(session, doc_id: str, epoch: str) -> int:
    """该文档在指定代次上已有的分块行数（幂等守卫的依据）"""
    return (
        session.query(func.count(KnowledgeChunk.id))
        .filter(
            and_(
                KnowledgeChunk.doc_id == doc_id,
                KnowledgeChunk.chunk_epoch == epoch,
            )
        )
        .scalar()
        or 0
    )


def embed_in_batches(
    texts: Sequence[str],
    model: str,
    *,
    batch: int = EMBED_BATCH,
    verbose: bool = True,
) -> List[List[float]]:
    """分批向量化并**逐步打印进度**

    为什么必须分批且带进度：一次 ``embed(全部文本)`` 在长文档上是「要么全成、要么
    毫无痕迹」的操作。实测本机 635 块的单次调用在数分钟后进程消失——日志里既没有
    异常也没有进度，无法判断死在嵌入、去重还是写入。分批后每一批的完成都会落进
    日志，长任务被外部中断时，那条最后的进度行就是唯一的定位证据。
    """
    client = get_embedding_client(model=model)
    vectors: List[List[float]] = []
    for start in range(0, len(texts), batch):
        vectors.extend(client.embed(list(texts[start:start + batch])))
        if verbose:
            print(f"      嵌入 {min(start + batch, len(texts))}/{len(texts)}", flush=True)
    return vectors


def rebuild_document(
    session,
    doc: KnowledgeDocument,
    kb: KnowledgeBase,
    target: str,
    encoder,
    model: str,
    epoch: str,
    verbose: bool = True,
) -> int:
    """重建**单篇**文档：分块 → 向量化 → 写 Qdrant → 写分块行 → 更新文档元数据

    写库顺序刻意是「先 Qdrant 后 MySQL」：若中途失败，最坏结果是 Qdrant 里留下
    一批**没有 MySQL 行**的点（孤儿向量，可由 ``repair_orphan_vectors.py`` 清理，
    且不可检索——回表查不到内容）。反过来先写 MySQL 则会产生「有行无向量」的
    状态，检索会命中一个取不到内容的分块。两者的可观测性不对等，故选前者。

    写入同样是分批的，且每批都打点：被测系统的真实行为是「可能被外部中断」，
    脚本必须让「中断发生在哪一批」在日志里可见（见 :func:`embed_in_batches`）。
    """
    from qdrant_client.models import PointStruct

    chunks = chunk_document(doc)
    if not chunks:
        raise ValueError(f"文档未产出任何分块: {doc.id} ({doc.file_name})")

    embeddings = embed_in_batches([c.text for c in chunks], model, verbose=verbose)
    if len(embeddings) != len(chunks):
        raise ValueError(
            f"嵌入返回数量不匹配: {len(embeddings)} != {len(chunks)} (doc={doc.id})"
        )

    client = get_qdrant_client()
    points: List[PointStruct] = []
    for offset, chunk in enumerate(chunks):
        vector_id = vector_id_for(doc.id, chunk.index, epoch)
        indices, values = encoder.document_vector(chunk.text)
        points.append(
            PointStruct(
                id=vector_id,
                vector=hybrid_point_vector(embeddings[offset], indices, values),
                payload={
                    "tenant_id": doc.tenant_id,
                    "kb_id": doc.kb_id,
                    "doc_id": doc.id,
                    "chunk_index": chunk.index,
                },
            )
        )

    for start in range(0, len(points), UPSERT_BATCH):
        client.upsert(collection_name=target, points=points[start:start + UPSERT_BATCH])
        if verbose:
            print(f"      写入 Qdrant {min(start + UPSERT_BATCH, len(points))}/{len(points)}",
                  flush=True)

    # 幂等守卫：同代次的行先删后插（重复执行本脚本不应产生重复行/撞唯一索引）。
    removed = (
        session.query(KnowledgeChunk)
        .filter(
            and_(
                KnowledgeChunk.doc_id == doc.id,
                KnowledgeChunk.chunk_epoch == epoch,
            )
        )
        .delete(synchronize_session=False)
    )
    if removed and verbose:
        print(f"      已清理同代次旧行 {removed} 行（重复执行本脚本）")

    for chunk in chunks:
        session.add(
            KnowledgeChunk(
                tenant_id=doc.tenant_id,
                kb_id=doc.kb_id,
                doc_id=doc.id,
                content=chunk.text,
                chunk_index=chunk.index,
                source_page=chunk.page,
                source_page_end=chunk.page_end,
                heading_path=chunk.heading_path,
                heading_path_mixed=chunk.heading_path_mixed,
                chunk_type=chunk_type_for(chunk.kind),
                vector_id=vector_id_for(doc.id, chunk.index, epoch),
                chunk_epoch=epoch,
            )
        )

    doc.chunk_count = len(chunks)
    # 重建期即翻代次：它是「这份文档现在有哪一代分块」的事实。分块列表与库级计数
    # 依据它，而检索侧不带代次过滤（见模块说明），因此切读前检索仍走旧集合、旧 id。
    doc.active_chunk_epoch = epoch
    session.flush()
    session.commit()
    return len(chunks)


def qdrant_point_count(collection: str) -> Optional[int]:
    """精确点数；集合不存在或探测失败返回 ``None``（调用方据此决定是否阻塞）"""
    try:
        return get_qdrant_client().count(collection_name=collection, exact=True).count
    except Exception:  # noqa: BLE001 - 验收路径宁可报「无法核验」也不抛栈
        return None


def do_cutover(session, kb: KnowledgeBase, target: str) -> None:
    """翻转灰度指针并重算库级计数

    只翻指针 + 计数，**不删旧代次分块行、不删旧集合**：两者都是回滚窗口的实体。

    同时把文档代次**对齐到本次切读的代次**（``config.chunk_epoch``）：切读与回滚必须
    对称，否则「先切读再回滚」之后文档代次停在新代次、指针却在旧集合上，管理端的
    分块列表与检索实际命中的内容对不上。目标集合按构造就是「用当前分块参数建的」，
    故当前代次即切读代次；若某文档根本没有该代次的行，说明它没被重建过，此时**不动它**
    并告警，而不是给它编造一个不存在的代次。
    """
    epoch = config.chunk_epoch
    aligned = 0
    for doc in live_documents(session, kb.id):
        if existing_epoch_chunk_count(session, doc.id, epoch):
            doc.active_chunk_epoch = epoch
            aligned += 1

    # 必须显式 flush：本项目的 ``sessionLocal`` 是 ``autoflush=False``，若不刷盘，
    # 下面那条「按当前代计数」的查询读到的仍是**改代次之前**的状态，于是留下
    # 「doc 代次已还原、kb.chunk_count 却还是新代次的数」这种自相矛盾的落库结果
    # （实测发生过：doc=1024-0 有 301 行，kb.chunk_count 却是 635）。
    session.flush()

    repo = KnowledgeChunkRepository(session, kb.tenant_id)
    live = repo.count_live_by_kb(kb.id)
    kb.active_collection = target
    kb.chunk_count = live
    session.commit()

    points = qdrant_point_count(target)
    print("\n切读完成：")
    print(f"  kb.active_collection = {target}")
    print(f"  代次对齐到            = {epoch}（{aligned} 篇文档）")
    print(f"  kb.chunk_count       = {live}")
    print(f"  目标集合点数(精确)    = {points if points is not None else '无法核验'}")
    if aligned == 0:
        print(
            f"  ⚠ 没有任何文档拥有代次 {epoch} 的分块行：目标集合可能是用**别的**"
            f"分块参数建的，切读后分块列表会为空，请核对后再继续"
        )
    if points is not None and points != live:
        print(
            f"  ⚠ 点数与存活行数不一致（{points} != {live}）："
            f"可能存在孤儿向量或半成品写入，请先跑 repair_orphan_vectors.py 对账"
        )
    print(f"  旧集合 kb_{kb.id} 与旧代次分块行**保留**（回滚窗口）")


def do_rollback(session, kb: KnowledgeBase, epoch: Optional[str]) -> None:
    """回滚：指针置空 + 代次还原

    代次还原的必要性：``doc.active_chunk_epoch`` 在重建期就已翻到新代次，若回滚时
    不回退，管理端的「文档分块列表」会显示新一代分块，而检索走的是旧集合——
    两者对不上。``--rollback-epoch`` 未给出时，取该文档**现存的最早代次**（本项目
    的重建流程下恰好只有一个更早的代次，取值无歧义）。
    """
    restored = 0
    docs = live_documents(session, kb.id)
    for doc in docs:
        if epoch is not None:
            if existing_epoch_chunk_count(session, doc.id, epoch):
                doc.active_chunk_epoch = epoch
                restored += 1
            continue
        oldest = (
            session.query(KnowledgeChunk.chunk_epoch)
            .filter(KnowledgeChunk.doc_id == doc.id)
            .order_by(KnowledgeChunk.chunk_epoch.asc())
            .limit(1)
            .scalar()
        )
        if oldest:
            doc.active_chunk_epoch = oldest
            restored += 1

    # 同 do_cutover：``autoflush=False`` 下必须先刷盘再按代计数，否则计数仍是旧值
    session.flush()

    kb.active_collection = None
    kb.chunk_count = KnowledgeChunkRepository(session, kb.tenant_id).count_live_by_kb(kb.id)
    session.commit()
    print(f"\n已回滚：kb.active_collection = NULL（检索改走 kb_{kb.id}）")
    print(f"  代次已还原的文档数 = {restored}/{len(docs)}")
    print(f"  kb.chunk_count      = {kb.chunk_count}")


def do_gc_old_epochs(session, kb: KnowledgeBase, keep_epoch: str) -> int:
    """物理回收**非当前代**的分块行（破坏性；仅在校验窗口关闭后调用）"""
    repo = KnowledgeChunkRepository(session, kb.tenant_id)
    total = 0
    for doc in live_documents(session, kb.id):
        total += repo.delete_superseded_by_doc_id(doc.id, keep_epoch=keep_epoch)
    session.commit()
    return total


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rebuild_knowledge_vectors",
        description="按当前分块参数重建知识库索引（可灰度、可回滚）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--kb-id", required=True, help="待重建知识库 id")
    parser.add_argument("--target-collection", default=None,
                        help="目标集合名（默认 kb_{kb_id}_v2）")
    parser.add_argument("--execute", action="store_true",
                        help="真正执行重建。缺省只打印计划，不写任何数据")
    parser.add_argument("--recreate", action="store_true",
                        help="目标集合已存在时先删除（防半成品续写）")
    parser.add_argument("--limit-docs", type=int, default=None,
                        help="只处理前 N 篇（链路验证）")
    # 切读 / 回滚 / 回收是**三个互斥的运维动作**，各自独立于重建。放进互斥组而不是
    # 允许叠加：同时给出两个动作时，无论先执行哪个都会留下与操作者预期不符的半成品
    # 状态（例如「先切读再回滚」等于没切，「先回收再回滚」会丢掉回滚实体）。
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--cutover", action="store_true",
                         help="把 active_collection 指向新集合并重算计数（重建完成后单独执行）")
    actions.add_argument("--rollback", action="store_true",
                         help="把 active_collection 置空（旧集合与旧行均在，立即生效）")
    actions.add_argument("--gc-old-epochs", action="store_true",
                         help="**破坏性**：物理删除非当前代的分块行，关闭回滚窗口")
    parser.add_argument("--rollback-epoch", default=None,
                        help="--rollback 时将 doc.active_chunk_epoch 还原为该代次"
                             "（缺省取该文档现存的最早代次）")
    parser.add_argument("--device", default=None, help="嵌入推理设备（cpu / mps / cuda）")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.device:
        config.embedding_device = args.device

    session = sessionLocal()
    try:
        kb = (
            session.query(KnowledgeBase)
            .filter(
                and_(
                    KnowledgeBase.id == args.kb_id,
                    KnowledgeBase.deleted_at.is_(None),
                )
            )
            .first()
        )
        if kb is None:
            raise SystemExit(f"知识库不存在或已删除: {args.kb_id}")

        epoch = config.chunk_epoch
        target = target_collection_name(kb.id, args.target_collection)

        # 运维动作先于重建处理：它们各自独立于重建，且必须在「干跑缺省返回」之前
        # 分流。曾把 --cutover 判断放在 --execute 分支内，导致 `--cutover` 单独执行
        # 时静默落入干跑分支——打印了一堆计划、什么都没做，退出码还是 0。
        if args.execute and (args.cutover or args.rollback or args.gc_old_epochs):
            raise SystemExit(
                "--execute 只用于重建；切读/回滚/回收请单独执行（它们不重算向量）"
            )

        if args.rollback:
            do_rollback(session, kb, args.rollback_epoch)
            return 0

        if args.gc_old_epochs:
            removed = do_gc_old_epochs(session, kb, keep_epoch=epoch)
            print(f"已物理删除非当前代（≠ {epoch}）分块行 {removed} 行")
            print("⚠ 回滚窗口自此关闭：把 active_collection 置回旧集合将查不到内容")
            return 0

        if args.cutover:
            if not collection_exists(target):
                raise SystemExit(
                    f"目标集合不存在: {target}。请先执行重建（--execute），再切读"
                )
            do_cutover(session, kb, target)
            return 0

        docs = live_documents(session, kb.id, limit=args.limit_docs)
        if not docs:
            raise SystemExit(f"知识库下没有存活文档: {kb.id}")

        print(f"知识库 {kb.id}  {kb.name!r}")
        print(f"  存活文档数   = {len(docs)}")
        print(f"  当前 chunk_count = {kb.chunk_count}  (active_collection={kb.active_collection})")
        print(f"  嵌入模型     = {kb.embedding_model}")
        print(f"  目标集合     = {target}  (已存在={collection_exists(target)})")
        print(f"  新分块参数   = chunk_size={config.chunk_size} chunk_overlap={config.chunk_overlap}"
              f" → epoch={epoch}")

        # 干跑也要真实解析：预计块数只能来自真实分块结果，用旧的 chunk_count 折算会
        # 得出「+81%」这类看起来精确、实则基于旧参数的估算。
        print("\n解析并分块（真实链路，用于估算）：")
        started = time.perf_counter()
        planned: List[tuple] = []
        for doc in docs:
            chunks = chunk_document(doc)
            planned.append((doc.id, len(chunks)))
            print(f"  {doc.file_name}  {doc.file_type}  {doc.file_size/1e6:.2f} MB"
                  f"  →  {len(chunks)} 块（旧 {doc.chunk_count}）")
        total_chunks = sum(n for _, n in planned)
        parse_seconds = time.perf_counter() - started
        estimate = total_chunks / EMBED_CHUNKS_PER_SECOND
        print(f"  合计 {total_chunks} 块 | 解析+分块耗时 {parse_seconds:.1f}s")
        print(f"  预计嵌入耗时 ≈ {estimate/60:.1f} min（按 {EMBED_CHUNKS_PER_SECOND} 块/秒估算）")

        if not args.execute:
            print("\n（干跑）未写入任何数据。确认后加 --execute 执行。")
            return 0

        if collection_exists(target) and not args.recreate:
            raise SystemExit(
                f"目标集合已存在: {target}。若确为半成品，请加 --recreate 重建；"
                f"若已切读，请勿覆盖正在服务的集合"
            )

        dim = get_vector_size_for_model(kb.embedding_model)
        created = create_hybrid_collection(target, vector_size=dim, recreate=args.recreate)
        print(f"\n目标集合{'已创建' if created else '已存在且复用'}: {target} (vector_size={dim})")

        encoder = default_encoder()
        print("\n开始重建：")
        for doc in docs:
            started = time.perf_counter()
            count = rebuild_document(
                session, doc, kb, target, encoder, kb.embedding_model, epoch
            )
            print(f"  {doc.file_name} → {count} 块，{time.perf_counter()-started:.1f}s")

        # 重建后库级计数按「当前代存活行」口径重算，使 kb.chunk_count 与分块列表恒等。
        kb.chunk_count = KnowledgeChunkRepository(session, kb.tenant_id).count_live_by_kb(kb.id)
        session.commit()
        print(f"\n重建完成：kb.chunk_count = {kb.chunk_count}")
        print(f"  目标集合点数(精确) = {qdrant_point_count(target)}")
        print("\n未切读：检索仍走旧集合。抽验新集合内容无误后，执行 --cutover 切读。")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
