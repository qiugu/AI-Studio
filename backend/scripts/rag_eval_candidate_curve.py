#!/usr/bin/env python
"""Phase 4.3 调参依据：测量「宽召回规模 candidate_k → 段落级 Recall 上限」曲线。

为什么要单独测这条曲线
----------------------

精排**只能重排已经召回的候选**，因此 ``candidate_k`` 直接决定质量天花板：
候选里没有相关段落，精排再强也捞不回来。反之，``candidate_k`` 每扩大一倍，
精排成本就线性翻倍——而本机实测精排吞吐仅 2.7 对/秒（MPS），代价不可忽略。

因此选 ``candidate_k`` 的依据不是「越大越好」，而是**天花板何时不再增长**：
曲线进入平台区的那一点，就是性价比拐点。

实现约定：为保证与正式评测同口径，本脚本直接复用
:class:`~app.rag_eval.retrievers.PassageMappedRetriever` +
:class:`~app.rag_eval.retrievers.QdrantRetriever`，不另写检索逻辑。
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import List, Sequence, Tuple

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# 本脚本需要真实的 Qdrant 连接配置，因此**不**跳过 backend/.env（与
# index_rag_eval_corpus.py 相反：后者只需要本地模型，不需要任何凭据）。

DEFAULT_DATA_DIR = BACKEND_DIR / "data" / "rag_eval"
DEFAULT_KS = (10, 20, 50, 100, 200)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="测量 candidate_k 的段落级 Recall 上限曲线",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    parser.add_argument("--ks", default=",".join(str(k) for k in DEFAULT_KS),
                        help="待测量的候选规模列表（逗号分隔）")
    parser.add_argument("--oversample", type=int, default=5,
                        help="分块折叠为段落时的索取倍数（与正式评测保持一致）")
    parser.add_argument("--out", default=None, help="结果 JSON 输出路径")
    return parser


def load_golden(path: Path) -> List[dict]:
    records: List[dict] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    data_dir = Path(args.data_dir)

    from app.rag_eval.index_manifest import load_index_manifest
    from app.rag_eval.retrievers import PassageMappedRetriever, QdrantRetriever

    index = load_index_manifest(data_dir)
    golden = load_golden(data_dir / "golden.jsonl")
    ks: Tuple[int, ...] = tuple(sorted({int(part) for part in args.ks.split(",") if part.strip()}))

    retriever = PassageMappedRetriever(
        QdrantRetriever(collection_name=index.collection),
        index.id_map,
        oversample=args.oversample,
    )

    print(f"collection={index.collection} 段落={index.n_passages} 分块={index.n_chunks}")
    print(f"查询数={len(golden)}  测量 candidate_k ∈ {ks}")
    print()

    # 逐条查询、逐个 k 取「段落级前 k」，统计 Recall@k（分母=该查询完整相关集）
    recalls: dict[int, List[float]] = {k: [] for k in ks}
    pool_sizes: List[int] = []
    for record in golden:
        relevant = {str(item["id"]) if isinstance(item, dict) else str(item)
                    for item in record["relevant"]}
        pool_sizes.append(len(relevant))
        for k in ks:
            result = retriever.retrieve(record["query"], top_k=k)
            hit = len(set(result.ids) & relevant)
            recalls[k].append(hit / len(relevant))

    curve = []
    print(f"{'candidate_k':>12} {'Recall上限':>12} {'相对@10增益':>14}")
    print("-" * 42)
    base = statistics.fmean(recalls[ks[0]]) if recalls[ks[0]] else 0.0
    for k in ks:
        mean = statistics.fmean(recalls[k]) if recalls[k] else 0.0
        curve.append({"candidate_k": k, "recall_ceiling": round(mean, 4)})
        print(f"{k:>12} {mean:>12.4f} {mean - base:>+13.4f}")

    payload = {
        "collection": index.collection,
        "n_queries": len(golden),
        "relevant_per_query_mean": round(statistics.fmean(pool_sizes), 4) if pool_sizes else 0.0,
        "oversample": args.oversample,
        "curve": curve,
        "note": (
            "Recall 上限 = 宽召回候选集内相关段落的覆盖率。精排只能在此上限内重排；"
            "曲线进入平台区即 candidate_k 的性价比拐点。"
        ),
    }

    out_path = Path(args.out) if args.out else data_dir / "reports" / "candidate-k-curve.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print(f"结果：{out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
