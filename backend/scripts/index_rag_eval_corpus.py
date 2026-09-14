#!/usr/bin/env python
"""Phase 2.4–2.6：把采样语料走**真实分块 + 向量化 + Qdrant** 链路入库，并做分块切断检测。

产出（默认 ``backend/data/rag_eval/``）::

    chunks.jsonl           每个索引点一行：``{point_id, passage_id, chunk_index, text}``
    index_manifest.json    索引清单：collection / 模型 / 维度 / 分块参数 / 统计
    cut_report.json        分块切断检测报告

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
from typing import Dict, List, Sequence, Tuple

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# 本脚本只需要 Qdrant 连接（默认 localhost）与本地 embedding 模型，不需要数据库凭据，
# 故默认跳过 backend/.env，保证在无凭据环境（含 CI）也能运行。
os.environ.setdefault("AI_STUDIO_SKIP_ENV_FILE", "1")

from app.core.config import config  # noqa: E402
from app.core.vector_db import get_or_create_collection, get_qdrant_client  # noqa: E402
from app.rag_eval.dataset import load_jsonl  # noqa: E402
from app.utils.document import TextSplitter  # noqa: E402
from app.utils.embedding import get_embedding_client  # noqa: E402

DEFAULT_DATA_DIR = BACKEND_DIR / "data" / "rag_eval"
DEFAULT_KB_SLUG = "rageval_t2r"
DEFAULT_CHUNK_SIZE = 1024
DEFAULT_CHUNK_OVERLAP = 128
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

    Note:
        当前 ``TextSplitter`` 的 ``chunk_overlap`` 实际未生效（已登记为 D11），
        此处仍显式传入线上参数，以便 Phase 5 修复后本脚本无需改动即可反映新行为。
    """
    splitter = TextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    chunks: List[dict] = []
    for passage_id, text in corpus:
        pieces = splitter.split(text)
        for index, piece in enumerate(pieces):
            chunks.append(
                {
                    "point_id": point_id_for(passage_id, index),
                    "passage_id": passage_id,
                    "chunk_index": index,
                    "text": piece,
                }
            )
    return chunks


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


def upsert_points(collection: str, chunks: Sequence[dict], vectors: Sequence[Sequence[float]]) -> None:
    """写入 Qdrant；payload 只带定位所需字段（与线上 payload 风格一致）"""
    from qdrant_client.models import PointStruct

    client = get_qdrant_client()
    for start in range(0, len(chunks), UPSERT_BATCH):
        batch = chunks[start:start + UPSERT_BATCH]
        points = [
            PointStruct(
                id=item["point_id"],
                vector=list(vectors[start + offset]),
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

    collection = f"kb_{args.kb_slug}"
    if args.recreate:
        client = get_qdrant_client()
        existing = {c.name for c in client.get_collections().collections}
        if collection in existing:
            client.delete_collection(collection_name=collection)
            print(f"      已删除旧 collection: {collection}")
    collection = get_or_create_collection(args.kb_slug, vector_size=dim)
    print(f"[2/5] collection 就绪: {collection}")

    corpus = load_corpus(corpus_path, limit=args.limit_passages)
    print(f"[3/5] 载入语料 {len(corpus)} 段")
    chunks = build_chunks(corpus, args.chunk_size, args.chunk_overlap)
    print(f"      分块后 {len(chunks)} 块（平均 {len(chunks)/max(len(corpus),1):.3f} 块/段）")

    print("[4/5] 向量化并写入 Qdrant")
    vectors = embed_chunks(chunks, model)
    upsert_points(collection, chunks, vectors)

    print("[5/5] 写出索引清单与切断检测报告")
    chunks_path = data_dir / "chunks.jsonl"
    with chunks_path.open("w", encoding="utf-8") as handle:
        for item in chunks:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")

    manifest = {
        "collection": collection,
        "kb_slug": args.kb_slug,
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
    }
    (data_dir / "index_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    corpus_len = {passage_id: len(text) for passage_id, text in corpus}
    cut_report = build_cut_report(golden_path, chunks, corpus_len) if golden_path.exists() else {}
    (data_dir / "cut_report.json").write_text(
        json.dumps(cut_report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"      {chunks_path} ({chunks_path.stat().st_size/1e6:.1f} MB)")
    print(f"      {data_dir / 'index_manifest.json'}")
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
