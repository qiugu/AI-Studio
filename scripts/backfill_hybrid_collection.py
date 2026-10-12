#!/usr/bin/env python
"""把稠密集合回填为「命名稠密 + 命名稀疏」布局（混合检索的前置步骤）

为什么必须回填而不能原地升级
----------------------------
Qdrant **不支持向已存在的匿名稠密集合追加稀疏向量**（实测报
``Not existing vector name error``）。因此混合检索要求集合从一开始就是「命名稠密 +
命名稀疏」布局，既有集合只能重建。本脚本把旧集合的内容写入一个**新名字**的集合
（默认 ``<源集合>_hybrid``），切读失败时可立刻退回旧集合——不做原地改名。

稠密向量无需重算
----------------
直接从源集合 ``scroll`` 出稠密向量原样写入目标集合（实测可行），因此回填成本几乎
只有「读出 + 写入 + 稀疏编码」，不涉及模型推理。稀疏向量由分块原文确定性推导，
不需要 GPU、不需要网络、不需要 Embedding 服务。

安全设计
--------
- **默认只读**：不加 ``--execute`` 时只输出计划（源集合规模、文本覆盖率、
  预计写入量），不创建集合、不写入任何数据。
- **目标不存在才写**：目标集合已存在时默认拒绝执行，避免把半成品当成成品继续追加。
  确定要重跑时显式加 ``--recreate``。
- **文本覆盖率可审计**：源集合中拿不到原文的 point 会被**跳过并计数**，不会写入
  「只有稠密、没有稀疏」的半残 point——那样的 point 在混合检索里永远只能靠稠密
  分支被召回，却会让回填看起来「成功」。
- **可抽样**：``--sample N`` 只回填前 N 个 point，用于在正式回填前验证链路。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

SCROLL_BATCH = 256


def load_texts_from_jsonl(
    path: Path,
    id_field: str = "point_id",
    text_field: str = "text",
) -> Dict[str, str]:
    """从 jsonl 读取 ``{point_id: text}``

    索引构建期落盘的 ``chunks.jsonl`` 就是这种结构（见 ``app/rag_eval/index_manifest.py``）。
    这里刻意不复用 ``IndexManifest``：本脚本同时服务评测语料与业务知识库，
    后者没有段落映射的概念，引入清单模型会带来不必要的耦合。
    """
    mapping: Dict[str, str] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            point_id = record.get(id_field)
            text = record.get(text_field)
            if point_id is None or text is None:
                continue
            mapping[str(point_id)] = text
    return mapping


def load_texts_from_mysql(kb_id: str) -> Dict[str, str]:
    """从业务库读取 ``{vector_id: content}``（仅存活分块）"""
    from sqlalchemy import text as sql_text

    from app.core.database import sessionLocal

    session = sessionLocal()
    try:
        rows = session.execute(
            sql_text(
                "SELECT c.vector_id, c.content FROM knowledge_chunks AS c "
                "JOIN knowledge_documents AS d ON d.id = c.doc_id AND d.deleted_at IS NULL "
                "WHERE c.kb_id = :kb_id AND c.deleted_at IS NULL AND c.vector_id IS NOT NULL"
            ),
            {"kb_id": kb_id},
        ).fetchall()
        return {str(row[0]): row[1] for row in rows}
    finally:
        session.close()


def iter_source_points(client, collection_name: str, sample: Optional[int]):
    """分批 scroll 源集合（含向量），产出 ``(id, dense_vector)``"""
    offset = None
    emitted = 0
    while True:
        points, offset = client.scroll(
            collection_name=collection_name,
            limit=SCROLL_BATCH,
            offset=offset,
            with_payload=False,
            with_vectors=True,
        )
        for point in points:
            if sample is not None and emitted >= sample:
                return
            emitted += 1
            yield str(point.id), point.vector
        if offset is None:
            return


def _dense_of(vector) -> Optional[Sequence[float]]:
    """取出稠密向量；兼容匿名布局（list）与命名布局（dict）"""
    from app.core.vector_db import NAMED_DENSE_VECTOR

    if isinstance(vector, dict):
        return vector.get(NAMED_DENSE_VECTOR)
    return vector


def backfill(
    source: str,
    target: str,
    texts: Dict[str, str],
    *,
    execute: bool,
    recreate: bool,
    sample: Optional[int],
    batch_size: int,
    use_idf: bool,
) -> int:
    from qdrant_client.models import PointStruct

    from app.core.vector_db import (
        create_hybrid_collection,
        get_qdrant_client,
        hybrid_point_vector,
    )
    from app.utils.sparse import SparseEncoder

    client = get_qdrant_client()
    collections = {item.name for item in client.get_collections().collections}
    if source not in collections:
        print(f"[error] source collection not found: {source}", file=sys.stderr)
        return 2

    info = client.get_collection(source)
    vector_size = info.config.params.vectors
    if isinstance(vector_size, dict):
        vector_size = vector_size.get("dense")
    vector_size = vector_size.size
    total = info.points_count or 0

    print("=" * 66)
    print("混合布局回填计划")
    print("=" * 66)
    print(f"源集合            : {source}（{total} 个 point，维度 {vector_size}）")
    print(f"目标集合          : {target}")
    print(f"文本表规模        : {len(texts)}")
    print(f"稀疏编码器        : {'带 IDF（语料拟合）' if use_idf else '无状态（可增量）'}")
    if sample is not None:
        print(f"抽样              : 仅前 {sample} 个 point")
    print("-" * 66)

    if target in collections and not recreate:
        print(f"[error] target {target} already exists; pass --recreate to overwrite", file=sys.stderr)
        return 2

    if not execute:
        print("结论：只读计划。加 --execute 执行回填（会创建目标集合并写入数据）。")
        print("=" * 66)
        return 0

    create_hybrid_collection(target, vector_size, recreate=recreate, client=client)
    print(f"[qdrant] 已创建 {target}（命名稠密 + 命名稀疏）", flush=True)

    encoder: Optional[SparseEncoder] = None
    if use_idf:
        # 拟合需要全量原文；对超大语料可用 --idf-sample 限制，但那会引入近似。
        encoder = SparseEncoder.fit(list(texts.values()))
        print(f"[sparse] 语料拟合完成：avgdl={encoder.avgdl:.1f}，词元数={len(encoder.idf or {})}", flush=True)
    else:
        encoder = SparseEncoder(
            k1=_k1(), b=_b(), avgdl=_avgdl(), idf=None
        )
        print(f"[sparse] 无状态编码器：avgdl={encoder.avgdl:.1f}", flush=True)

    written = 0
    skipped = 0
    buffer: List[PointStruct] = []
    for point_id, raw_vector in iter_source_points(client, source, sample):
        dense = _dense_of(raw_vector)
        content = texts.get(point_id)
        if dense is None or content is None:
            skipped += 1
            continue
        sparse_indices, sparse_values = encoder.document_vector(content)
        buffer.append(
            PointStruct(
                id=point_id,
                vector=hybrid_point_vector(dense, sparse_indices, sparse_values),
            )
        )
        if len(buffer) >= batch_size:
            client.upsert(collection_name=target, points=buffer)
            written += len(buffer)
            buffer = []
            if written % (batch_size * 10) == 0:
                print(f"[qdrant] 已写入 {written}", flush=True)
    if buffer:
        client.upsert(collection_name=target, points=buffer)
        written += len(buffer)

    print(f"[qdrant] 完成：写入 {written}，跳过（缺原文或稠密向量）{skipped}", flush=True)
    final = client.get_collection(target).points_count
    print(f"[qdrant] {target} 现有 {final} 个 point")
    print("-" * 66)
    ok = skipped == 0 and (sample is not None or final == total)
    print(f"结论：{'回填完整' if ok else '回填**不完整**，请检查跳过的 point'}")
    print("=" * 66)
    return 0 if ok else 1


def _k1() -> float:
    from app.core.config import config

    return config.retrieval_sparse_k1


def _b() -> float:
    from app.core.config import config

    return config.retrieval_sparse_b


def _avgdl() -> float:
    from app.core.config import config

    return config.retrieval_sparse_avgdl


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="backfill_hybrid_collection",
        description=(
            "把稠密集合回填为「命名稠密 + 命名稀疏」布局（混合检索前置步骤）。"
            "Qdrant 无法向匿名稠密集合追加稀疏向量，故必须新建集合并回填。"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--source", required=True, help="源集合名，例如 kb_rageval_t2r")
    parser.add_argument("--target", required=True, help="目标集合名，例如 kb_rageval_t2r_hybrid")
    parser.add_argument("--texts-jsonl", default=None, help="分块原文 jsonl 路径（评测语料）")
    parser.add_argument("--from-mysql", default=None, help="改为从业务库读取：知识库 id")
    parser.add_argument("--id-field", default="point_id", help="jsonl 中作为 point id 的字段名")
    parser.add_argument("--text-field", default="text", help="jsonl 中作为原文的字段名")
    parser.add_argument("--execute", action="store_true", help="实际执行（默认只读计划）")
    parser.add_argument("--recreate", action="store_true", help="目标已存在时先删除重建")
    parser.add_argument("--sample", type=int, default=None, help="只回填前 N 个 point（链路验证）")
    parser.add_argument("--batch-size", type=int, default=SCROLL_BATCH, help="upsert 批大小")
    parser.add_argument("--idf", action="store_true", help="使用语料拟合的 IDF（默认无状态）")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    if not args.texts_jsonl and not args.from_mysql:
        print("[error] 需要 --texts-jsonl 或 --from-mysql 之一", file=sys.stderr)
        return 2

    if args.texts_jsonl:
        path = Path(args.texts_jsonl)
        if not path.exists():
            print(f"[error] texts jsonl not found: {path}", file=sys.stderr)
            return 2
        texts = load_texts_from_jsonl(path, args.id_field, args.text_field)
    else:
        texts = load_texts_from_mysql(args.from_mysql)

    print(f"[ok] 载入原文 {len(texts)} 条", flush=True)
    return backfill(
        args.source,
        args.target,
        texts,
        execute=args.execute,
        recreate=args.recreate,
        sample=args.sample,
        batch_size=args.batch_size,
        use_idf=args.idf,
    )


if __name__ == "__main__":
    raise SystemExit(main())
