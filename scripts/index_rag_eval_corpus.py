#!/usr/bin/env python
"""Phase 2.4–2.6：把采样语料走**真实分块 + 向量化 + Qdrant** 链路入库，并做分块切断检测。

产出（默认 ``backend/data/rag_eval/``，可用 ``--out-dir`` 改到别处）::

    chunks.jsonl           每个索引点一行：``{point_id, passage_id, chunk_index, text}``
    index_manifest.json    索引清单：collection / 模型 / 维度 / 分块参数 / 布局 / 统计
    cut_report.json        分块切断检测报告
    sparse_encoder.json    仅 ``--idf``：拟合出的 k1/b/avgdl/idf（供复现与对账）

为什么需要 ``--out-dir``（而不是永远写回 ``--data-dir``）
--------------------------------------------------------

稠密与混合两次索引的 ``chunks.jsonl`` 必须能**同时留存**：Phase 5 的对照结论
（「混合相对稠密提升了多少」）依赖两次运行的分块集合完全一致，若第二次运行把
第一次的产物覆盖掉，事后就无法回答「两次用的是不是同一份分块」。因此两次运行
各写一个目录，把「同一份分块」变成可核对的事实而非假设。

``--hybrid`` 与 ``--idf`` 的关系
--------------------------------

两者独立：``--hybrid`` 决定**集合布局**（命名稠密 + 命名稀疏，混合检索的前提），
``--idf`` 决定**文档侧稀疏权重**（默认无状态、IDF 恒为 1；开启后用语料拟合的 IDF，
离线对照下增益约高 30%，但**新增文档会使 df/avgdl 失效**，故只用于离线评测）。
查询侧一律是二值权重（词出现即 1），故评测运行器无需读取 ``sparse_encoder.json``——
该文件是给复现与对账看的。

为什么必须走真实链路
--------------------

评测要回答的是「给线上检索加 Reranker 能提升多少」，因此被评测的召回侧必须与线上
逐一对应：同一 ``TextSplitter``、同一 ``EmbeddingClient``、同一 ``search_points``。
一旦评测侧另写一份简化实现，测出来的增益就无法外推到线上——这是评测体系最常见的失效方式。

段落粒度 vs 分块粒度
--------------------

基准的标准答案是**段落**，而索引里存的是**分块**。一个段落可能被切成多个分块，
若在分块粒度上算 Recall，指标会随 ``chunk_size`` 变化而变——Phase 5 正要调整分块
参数，那样就无法比较。因此：

* 索引里每个分块都带 ``passage_id`` payload；
* 评测时把命中分块**映射回段落并去重**，在段落粒度上打分；
* 映射关系固化为 ``chunks.jsonl``（构建期确定），避免运行时二次推导。

这样「切断」不会人为压低 Recall 上限；切断检测报告的用途转为**披露信号稀释程度**：
被切开的段落，其单个分块只承载部分语义，匹配质量会下降。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple, Union

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# 本脚本只需要 Qdrant 连接（默认 localhost）与本地 embedding 模型，不需要数据库凭据，
# 故默认跳过 backend/.env，保证在无凭据环境（含 CI）也能运行。
os.environ.setdefault("AI_STUDIO_SKIP_ENV_FILE", "1")

from app.core.config import config  # noqa: E402
from app.core.vector_db import (  # noqa: E402
    collection_name_for,
    get_or_create_collection,
    get_qdrant_client,
    hybrid_point_vector,
)
from app.rag_eval.dataset import load_jsonl  # noqa: E402
from app.utils.document import TextSegment, TextSplitter  # noqa: E402
from app.utils.embedding import get_embedding_client  # noqa: E402
from app.utils.sparse import SparseEncoder, default_encoder  # noqa: E402

DEFAULT_DATA_DIR = BACKEND_DIR / "data" / "rag_eval"
DEFAULT_KB_SLUG = "rageval_t2r"
# 分块默认值取自**配置**而非写死，避免「评测用的分块参数」与「线上入库的分块参数」
# 悄悄漂移——一旦漂移，评测结论就不再能代表线上行为。命令行仍可覆盖以便做参数扫描。
DEFAULT_CHUNK_SIZE = config.chunk_size
DEFAULT_CHUNK_OVERLAP = config.chunk_overlap
EMBED_BATCH = 32
UPSERT_BATCH = 256

#: 与线上同样的 uuid5 命名空间派生方式，保证同一段落+序号总得到同一个 point id，
#: 重复执行本脚本不会产生重复索引。
_UUID_NAMESPACE = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


def point_id_for(passage_id: str, chunk_index: int) -> str:
    """派生稳定的索引点 id（Qdrant 只接受 uuid 或整数，故必须派生）"""
    return str(uuid.uuid5(_UUID_NAMESPACE, f"{passage_id}#{chunk_index}"))


def load_corpus(path: Path, limit: int | None = None) -> List[Tuple[str, str]]:
    """读取 ``corpus.jsonl``，返回 ``[(id, text), ...]``"""
    records = load_jsonl(path)
    corpus = [(str(record["id"]), str(record["text"])) for record in records]
    if limit is not None:
        corpus = corpus[:limit]
    return corpus


def build_chunks(
    corpus: Sequence[Tuple[str, str]],
    chunk_size: int,
    chunk_overlap: int,
) -> List[dict]:
    """按线上同一 ``TextSplitter`` 分块，返回分块记录列表

    走 ``split_segments([TextSegment(text)])`` 而非 ``split(text)``：评测语料的
    每段本身就是一段纯文本，两者结果**当下**等价，但只有前者与线上入库
    (``knowledge_processor``) 是同一调用路径。若将来线上改为「按页/按标题切段
    再段内分块」，此处会自动跟随，不会悄悄分叉成两套分块口径。

    ``chunk_overlap`` 现在**真实生效**（D11 已修复）：块之间会有实际重叠，
    因此块数会随重叠增大而增加，这是与历史基线比较时必须注意的口径变化。
    """
    splitter = TextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    chunks: List[dict] = []
    for passage_id, text in corpus:
        pieces = splitter.split_segments([TextSegment(text=text)])
        for index, piece in enumerate(pieces):
            chunks.append(
                {
                    "point_id": point_id_for(passage_id, index),
                    "passage_id": passage_id,
                    "chunk_index": index,
                    "text": piece.text,
                }
            )
    return chunks


def build_sparse_encoder(
    chunks: Sequence[dict],
    use_idf: bool,
    sample_limit: Optional[int] = None,
) -> SparseEncoder:
    """构造文档侧稀疏编码器

    ``use_idf=False``（默认）取生产一致的**无状态**编码器：IDF 恒为 1，
    编码结果与语料规模无关，因此评测索引与线上索引在权重口径上逐位一致。

    ``use_idf=True`` 在**分块文本**（而非段落原文）上拟合 df/avgdl：被索引的
    就是分块，用段落原文统计会让长度归一化项失真。该模式的用途是离线对照
    「IDF 能带来多少增益」，代价是语料一变 df 即失效，故不作为默认。
    """
    if not use_idf:
        return default_encoder()
    return SparseEncoder.fit([item["text"] for item in chunks], sample_limit=sample_limit)


def build_point_vectors(
    dense_vectors: Sequence[Sequence[float]],
    chunks: Sequence[dict],
    encoder: Optional[SparseEncoder],
) -> List[Union[List[float], Dict]]:
    """把稠密向量（+ 可选稀疏向量）组装为可直接 upsert 的向量字段

    返回项的形态取决于布局：``encoder is None`` 时是匿名稠密列表（旧布局，
    与改造前逐位一致）；否则是 ``{"dense": [...], "text": SparseVector}``
    ——向量名由 :func:`hybrid_point_vector` 单点给出，避免入库侧与检索侧
    各自硬编码名字而产生「写进去但查不到」的静默故障。
    """
    if encoder is None:
        return [list(vector) for vector in dense_vectors]

    vectors: List[Union[List[float], Dict]] = []
    for offset, item in enumerate(chunks):
        indices, values = encoder.document_vector(item["text"])
        vectors.append(hybrid_point_vector(dense_vectors[offset], indices, values))
    return vectors


def embed_chunks(chunks: Sequence[dict], model: str) -> List[List[float]]:
    """批量向量化；进度按批次打印，便于长任务观察"""
    client = get_embedding_client(model=model)
    vectors: List[List[float]] = []
    started = time.perf_counter()
    for start in range(0, len(chunks), EMBED_BATCH):
        batch = chunks[start:start + EMBED_BATCH]
        vectors.extend(client.embed([item["text"] for item in batch]))
        done = min(start + EMBED_BATCH, len(chunks))
        if done % (EMBED_BATCH * 20) == 0 or done == len(chunks):
            rate = done / max(time.perf_counter() - started, 1e-6)
            print(f"      向量化 {done}/{len(chunks)} ({rate:.0f} 条/秒)", flush=True)
    return vectors


def upsert_points(
    collection: str,
    chunks: Sequence[dict],
    vectors: Sequence[Union[Sequence[float], Dict]],
) -> None:
    """写入 Qdrant；payload 只带定位所需字段（与线上 payload 风格一致）

    ``vectors`` 的元素形态随布局而变（匿名稠密列表 / 命名稠密+稀疏字典），
    此处**不做任何转换**直接透传：``list(vector)`` 之类的"规范化"会命中字典
    并把它变成键列表，最终写入一个维度错乱的向量——Qdrant 不会报错，
    只会让检索结果与文本对不上。
    """
    from qdrant_client.models import PointStruct

    client = get_qdrant_client()
    for start in range(0, len(chunks), UPSERT_BATCH):
        batch = chunks[start:start + UPSERT_BATCH]
        points = [
            PointStruct(
                id=item["point_id"],
                vector=vectors[start + offset],
                payload={
                    "passage_id": item["passage_id"],
                    "chunk_index": item["chunk_index"],
                    "source": "rag_eval",
                },
            )
            for offset, item in enumerate(batch)
        ]
        client.upsert(collection_name=collection, points=points)
        print(f"      写入 {min(start + UPSERT_BATCH, len(chunks))}/{len(chunks)}", flush=True)


def build_cut_report(
    golden_path: Path,
    chunks: Sequence[dict],
    corpus_len: Dict[str, int],
) -> dict:
    """分块切断检测（Phase 2.6）

    判定「相关段落被切开」即该段落产生了 >1 个分块。用途是**披露信号稀释程度**，
    而非剔除查询：映射回段落后 Recall 上限不受影响，但被切开的段落其单个分块只
    承载部分语义，实际匹配质量会更低——这属于被评测系统的真实行为，应当被观测，
    而不是从数据集里隐藏。
    """
    chunks_per_passage = Counter(item["passage_id"] for item in chunks)

    queries = load_jsonl(golden_path)
    split_relevant = 0
    total_relevant = 0
    affected_queries: List[dict] = []
    for record in queries:
        relevant = [str(item["id"]) for item in record["relevant"]]
        split_here = [doc_id for doc_id in relevant if chunks_per_passage.get(doc_id, 0) > 1]
        total_relevant += len(relevant)
        split_relevant += len(split_here)
        if split_here:
            affected_queries.append(
                {
                    "query_id": record["query_id"],
                    "n_relevant": len(relevant),
                    "n_split_relevant": len(split_here),
                    "split_passage_ids": split_here,
                }
            )

    distribution = Counter(chunks_per_passage.get(str(pid), 0) for pid in corpus_len)
    return {
        "n_passages": len(corpus_len),
        "n_chunks": len(chunks),
        "chunks_per_passage_distribution": {str(k): v for k, v in sorted(distribution.items())},
        "passages_with_multiple_chunks": sum(
            count for size, count in distribution.items() if size > 1
        ),
        "n_relevant_total": total_relevant,
        "n_relevant_split": split_relevant,
        "split_relevant_ratio": round(split_relevant / total_relevant, 4) if total_relevant else 0.0,
        "n_queries_affected": len(affected_queries),
        "affected_queries": affected_queries,
        "note": (
            "被切开的段落由 chunks.jsonl 映射回段落粒度打分，不压低 Recall 上限；"
            "本报告用于披露信号稀释程度。"
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="将采样语料走真实链路入库 Qdrant，并做分块切断检测",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR), help="数据集目录")
    parser.add_argument(
        "--out-dir",
        default=None,
        help="产物输出目录（chunks/manifest/cut_report 落在此处；缺省与 --data-dir 相同）。"
             "稠密与混合两次索引应各写一个目录，否则后一次会覆盖前一次的产物，"
             "导致「两次用的是不是同一份分块」无法事后核对",
    )
    parser.add_argument("--kb-slug", default=DEFAULT_KB_SLUG,
                        help="collection 标识，最终 collection 名为 kb_{slug}")
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE)
    parser.add_argument("--chunk-overlap", type=int, default=DEFAULT_CHUNK_OVERLAP)
    parser.add_argument("--device", default=None,
                        help="本地模型推理设备（cpu / mps / cuda），缺省沿用配置")
    parser.add_argument("--limit-passages", type=int, default=None,
                        help="仅索引前 N 段，用于快速冒烟验证")
    parser.add_argument("--recreate", action="store_true",
                        help="先删除同名 collection 再重建（全量重索引时必须显式指定）")

    layout = parser.add_argument_group("集合布局与稀疏权重")
    layout.add_argument(
        "--hybrid",
        action="store_true",
        help="以混合布局（命名稠密 + 命名稀疏）建集合并写入稀疏向量。"
             "不指定时与改造前逐位一致（匿名稠密集合）。"
             "注意：匿名稠密集合**无法原地升级**为混合布局，重索引时须配合 --recreate",
    )
    layout.add_argument(
        "--idf",
        action="store_true",
        help="文档侧稀疏权重改用**语料拟合的 IDF**（离线对照用，增益相对高约三成）。"
             "新增文档会使 df/avgdl 失效，故生产默认无状态（IDF 恒为 1）",
    )
    layout.add_argument(
        "--idf-sample-limit",
        type=int,
        default=None,
        help="--idf 拟合时只统计前 N 个分块（大规模语料下的抽样近似，控制耗时）",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    data_dir = Path(args.data_dir)
    corpus_path = data_dir / "corpus.jsonl"
    golden_path = data_dir / "golden.jsonl"
    if not corpus_path.exists():
        raise SystemExit(f"缺少语料文件 {corpus_path}，请先运行 prepare_rag_eval_dataset.py")

    # 设备必须在任何向量化调用之前生效：EmbeddingClient 调用时才读取该配置，
    # 模型实例按 (model, device) 进程级缓存。
    if args.device:
        config.embedding_device = args.device
    model = config.embedding_model
    dim = len(get_embedding_client(model=model).embed(["dimension probe"])[0])
    print(f"[1/5] 模型 {model} | device={config.embedding_device} | 维度={dim}")

    collection = collection_name_for(args.kb_slug)
    if args.recreate:
        client = get_qdrant_client()
        existing = {c.name for c in client.get_collections().collections}
        if collection in existing:
            client.delete_collection(collection_name=collection)
            print(f"      已删除旧 collection: {collection}")
    collection = get_or_create_collection(
        args.kb_slug, vector_size=dim, hybrid=args.hybrid
    )
    layout_name = "hybrid" if args.hybrid else "legacy_dense"
    print(f"[2/5] collection 就绪: {collection} | 布局={layout_name}")

    corpus = load_corpus(corpus_path, limit=args.limit_passages)
    print(f"[3/5] 载入语料 {len(corpus)} 段")
    chunks = build_chunks(corpus, args.chunk_size, args.chunk_overlap)
    print(f"      分块后 {len(chunks)} 块（平均 {len(chunks)/max(len(corpus),1):.3f} 块/段）")

    # 稀疏编码器只在混合布局下需要；稠密索引传入 None，走与改造前完全一致的路径。
    encoder = (
        build_sparse_encoder(chunks, args.idf, args.idf_sample_limit)
        if args.hybrid
        else None
    )
    if encoder is not None:
        print(
            f"      稀疏编码器: mode={'stateless' if encoder.is_stateless else 'idf'} "
            f"k1={encoder.k1} b={encoder.b} avgdl={encoder.avgdl:.1f}"
        )

    print("[4/5] 向量化并写入 Qdrant")
    dense_vectors = embed_chunks(chunks, model)
    point_vectors = build_point_vectors(dense_vectors, chunks, encoder)
    upsert_points(collection, chunks, point_vectors)

    print("[5/5] 写出索引清单与切断检测报告")
    out_dir = Path(args.out_dir) if args.out_dir else data_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    chunks_path = out_dir / "chunks.jsonl"
    with chunks_path.open("w", encoding="utf-8") as handle:
        for item in chunks:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")

    manifest = {
        "collection": collection,
        "kb_slug": args.kb_slug,
        "layout": layout_name,
        "embedding_model": model,
        "embedding_device": config.embedding_device,
        "vector_dim": dim,
        "chunk_size": args.chunk_size,
        "chunk_overlap": args.chunk_overlap,
        "n_passages": len(corpus),
        "n_chunks": len(chunks),
        "corpus_file": corpus_path.name,
        "golden_file": golden_path.name,
        "limit_passages": args.limit_passages,
        "out_dir": str(out_dir),
        # 稀疏编码器的参数一并固化：没有它，事后无法判断「两次混合运行的差异」
        # 是来自分块、来自 α，还是来自稀疏权重的拟合口径。
        "sparse_encoder": (
            {
                "mode": "stateless" if encoder.is_stateless else "idf",
                "k1": encoder.k1,
                "b": encoder.b,
                "avgdl": encoder.avgdl,
                "idf_terms": len(encoder.idf) if encoder.idf else 0,
                "idf_sample_limit": args.idf_sample_limit,
            }
            if encoder is not None
            else None
        ),
    }
    (out_dir / "index_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if encoder is not None and encoder.idf:
        (out_dir / "sparse_encoder.json").write_text(
            json.dumps(
                {
                    "k1": encoder.k1,
                    "b": encoder.b,
                    "avgdl": encoder.avgdl,
                    "idf": {str(index): value for index, value in encoder.idf.items()},
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    corpus_len = {passage_id: len(text) for passage_id, text in corpus}
    cut_report = build_cut_report(golden_path, chunks, corpus_len) if golden_path.exists() else {}
    (out_dir / "cut_report.json").write_text(
        json.dumps(cut_report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"      {chunks_path} ({chunks_path.stat().st_size/1e6:.1f} MB)")
    print(f"      {out_dir / 'index_manifest.json'}")
    if cut_report:
        print()
        print("分块切断检测：")
        print(f"  段落数 {cut_report['n_passages']} → 分块数 {cut_report['n_chunks']}")
        print(f"  被切开的段落: {cut_report['passages_with_multiple_chunks']}")
        print(f"  相关段落中被切开: {cut_report['n_relevant_split']}/{cut_report['n_relevant_total']}"
              f" ({cut_report['split_relevant_ratio']*100:.1f}%)")
        print(f"  受影响查询: {cut_report['n_queries_affected']}/{len(load_jsonl(golden_path))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
