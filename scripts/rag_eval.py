#!/usr/bin/env python
"""RAG 检索质量评测 CLI

用法示例::

    # 离线冒烟（无需 Qdrant / 模型权重，用确定性哈希检索器验证框架本身）
    python scripts/rag_eval.py --retriever in-memory \\
        --golden tests/fixtures/rag_eval/golden.jsonl \\
        --corpus tests/fixtures/rag_eval/corpus.jsonl --name smoke

    # 端到端基线（真实 Qdrant + 线上同一召回实现）
    python scripts/rag_eval.py --retriever qdrant \\
        --index-dir data/rag_eval --name baseline

    # 接入精排后对照（宽召回 + 本地 CrossEncoder）
    python scripts/rag_eval.py --retriever qdrant --index-dir data/rag_eval \\
        --rerank --candidate-k 100 --name reranked \\
        --baseline data/rag_eval/reports/baseline.json --fail-on-regression

退出码：``0`` 正常；``1`` 回归门禁未通过；``2`` 参数或环境错误。

实现约定
--------

1. **所有应用模块的导入都推迟到参数解析之后**。``app.core.config`` 在导入时即读取
   配置文件，若放在模块顶层，``--help`` 也会连带完成一次配置加载——既拖慢帮助
   信息输出，也让帮助命令在本机配置不可读时直接失败。

2. **``--index-dir`` 一旦提供，评测即切换到段落粒度**。此时 collection 与原文都
   由该目录的清单决定（``chunks.jsonl`` / ``index_manifest.json``），`--collection`
   可省略；检索链路最外层会套上 :class:`PassageMappedRetriever`，把分块命中折叠回
   基准的标准答案单元（段落）。不提供该参数时维持分块粒度，供离线夹具测试使用。

3. **精排在分块粒度上执行**。这是与线上一致的必要条件：线上精排看的是分块文本，
   若评测改用整段文本，测出的增益无法外推到线上。折叠到段落发生在精排之后。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Sequence, Tuple

if TYPE_CHECKING:  # 仅用于类型标注，避免在参数解析前触发应用模块导入
    from app.rag_eval import EvalRun, GoldenSet, IndexManifest, RegressionCheck

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

DEFAULT_DATA_DIR = BACKEND_DIR / "data" / "rag_eval"
DEFAULT_OUT_DIR = DEFAULT_DATA_DIR / "reports"


# ── 参数 ────────────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rag_eval",
        description="知识库检索质量评测：金标准集 → 召回 →（可选）精排 → 指标 → 报告",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--golden", help="金标准集 JSONL 路径；缺省取 --index-dir/golden.jsonl")
    parser.add_argument(
        "--retriever",
        choices=("in-memory", "qdrant"),
        default="in-memory",
        help="检索器类型：in-memory 离线确定性（默认）；qdrant 端到端真实链路",
    )
    parser.add_argument("--corpus", help="语料 JSONL 路径（in-memory 必填）")
    parser.add_argument("--collection", help="Qdrant collection 名称（qdrant 且无 --index-dir 时必填）")
    parser.add_argument(
        "--index-dir",
        help="索引清单目录（含 chunks.jsonl / index_manifest.json）。"
             "提供后评测在段落粒度进行，且原文与 collection 均取自清单。",
    )
    parser.add_argument(
        "--oversample",
        type=int,
        default=5,
        help="分块折叠为段落时的索取倍数（默认 5，实测约 1.47 块/段落）",
    )
    parser.add_argument(
        "--k",
        default="1,3,5,10",
        help="截断位置列表，逗号分隔（默认 1,3,5,10）",
    )
    parser.add_argument("--name", help="本次运行名称，用于报告标题与基线文件名")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="报告输出目录")

    hybrid = parser.add_argument_group("混合检索")
    hybrid.add_argument(
        "--hybrid",
        action="store_true",
        help="启用稠密 + 词法双路加权融合。要求目标集合为「命名稠密 + 命名稀疏」布局"
             "（先用 scripts/backfill_hybrid_collection.py 回填）。"
             "集合没有稀疏向量时**直接报错**，不会静默退化为纯稠密——"
             "否则会产出「标签写着 hybrid、数据其实是 dense-only」的失真结论。",
    )
    hybrid.add_argument(
        "--hybrid-alpha",
        type=float,
        default=None,
        help="稠密分支权重 α（默认取 config.retrieval_hybrid_alpha）。"
             "实测 α∈{0.6,0.7,0.8} 均优于纯稠密，0.7 最优。"
             "**不要改用等权 RRF**：实测 MRR@10 −7.33pp。",
    )
    hybrid.add_argument(
        "--hybrid-dense-k", type=int, default=200, help="稠密分支召回条数（默认 200）"
    )
    hybrid.add_argument(
        "--hybrid-sparse-k", type=int, default=200, help="词法分支召回条数（默认 200）"
    )

    rerank = parser.add_argument_group("精排")
    rerank.add_argument("--rerank", action="store_true", help="启用宽召回 + 精排")
    rerank.add_argument(
        "--candidate-k",
        type=int,
        default=100,
        help="宽召回条数（默认 100）。精排只能重排已召回的候选，该值即质量上限；"
             "实际候选集为 max(candidate_k, top_k × oversample)。",
    )
    rerank.add_argument("--rerank-model", default="BAAI/bge-reranker-v2-m3")
    rerank.add_argument("--rerank-device", default=None, help="cpu / mps / cuda，缺省沿用配置")
    rerank.add_argument("--rerank-batch-size", type=int, default=32)
    rerank.add_argument("--rerank-max-length", type=int, default=512)

    gate = parser.add_argument_group("回归门禁")
    gate.add_argument("--baseline", help="基线指标 JSON 路径（同时用于生成对照报告）")
    gate.add_argument("--gate-metric", default="recall@5", help="门禁指标（默认 recall@5）")
    gate.add_argument(
        "--max-drop-pp",
        type=float,
        default=1.0,
        help="允许的最大下降幅度，单位百分点（默认 1.0pp）",
    )
    gate.add_argument(
        "--fail-on-regression",
        action="store_true",
        help="门禁未通过时以退出码 1 结束（供 CI 使用）",
    )

    resume = parser.add_argument_group("续跑")
    resume.add_argument(
        "--resume",
        help="已有报告 JSON：跳过其中**已成功评分**的查询，只补跑缺失或失败的查询，"
             "再与历史结果合并输出。用于长任务（精排单次可达数十分钟）被外部原因"
             "中断后的接续——否则已付出的算力作废，且产物无法覆盖全部查询。",
    )
    return parser


# ── 数据装载 ────────────────────────────────────────────────────────────────


def load_corpus(path: str | Path) -> Dict[str, str]:
    """读取语料 JSONL，返回 ``{id: text}``"""
    from app.rag_eval.dataset import load_jsonl

    corpus: Dict[str, str] = {}
    for record in load_jsonl(path):
        corpus[str(record["id"])] = str(record["text"])
    if not corpus:
        raise SystemExit(f"语料为空：{path}")
    return corpus


def load_index(index_dir: str | Path) -> "IndexManifest":
    """读取索引清单；失败时给出可操作的提示而非栈回溯"""
    from app.rag_eval.index_manifest import load_index_manifest

    try:
        return load_index_manifest(index_dir)
    except (FileNotFoundError, ValueError) as exc:
        raise SystemExit(f"索引清单不可用：{exc}")


def load_previous_run(path: str | Path) -> "EvalRun":
    """读取历史报告并还原为 :class:`EvalRun`（``--resume`` 用）

    格式不可识别时直接报错退出，而不是「静默当作空历史」——后者会把一次续跑
    悄悄变成一次全量重跑，在数十分钟量级的精排评测上是代价很高的误解。
    """
    from app.rag_eval import EvalRun

    report_path = Path(path)
    if not report_path.exists():
        raise SystemExit(f"续跑报告不存在：{report_path}")
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"续跑报告不是合法 JSON：{report_path}（{exc}）")
    if not isinstance(payload, dict) or "per_query" not in payload:
        raise SystemExit(f"续跑报告缺少 per_query 字段，格式不可识别：{report_path}")
    return EvalRun.from_report(payload)


def build_text_lookup(
    corpus: Optional[Dict[str, str]],
    index: Optional["IndexManifest"],
) -> Callable[[str], Optional[str]]:
    """构造「检索单元 id → 原文」查询函数（精排输入）

    两种粒度对应两种来源，**不可混用**：

    * 有索引清单（段落粒度评测）—— 按 point id 取**分块原文**。精排必须看到
      分块文本，因为线上就是这么做的；改用整段文本会让评测高估精排增益。
    * 无索引清单（分块粒度，离线夹具）—— 检索单元即语料单元，直接查语料。
    """
    if index is not None:
        return index.chunk_text
    if corpus is None:
        return lambda _unit_id: None
    return corpus.get


# ── 组件装配 ────────────────────────────────────────────────────────────────


def build_rerank_fn(
    args: argparse.Namespace,
) -> Callable[[str, Sequence[Tuple[str, str]]], List[Tuple[str, float]]]:
    """装配本地 CrossEncoder 精排函数

    这里**主动预热模型**：加载失败通常源于权重缺失或设备配置错误，属于不会自愈的
    问题。让它在开始跑分前就失败，比跑完 100 条查询后才发现更有价值——后者会让人
    误以为「精排没有增益」。
    """
    from app.utils.reranker import RerankerUnavailable, get_reranker

    reranker = get_reranker(
        model_name=args.rerank_model,
        device=args.rerank_device,
        max_length=args.rerank_max_length,
        batch_size=args.rerank_batch_size,
    )
    try:
        reranker.warmup()
    except RerankerUnavailable as exc:
        raise SystemExit(f"精排模型不可用（reranker={args.rerank_model}）：{exc}")
    print(f"[ok] 精排模型已加载：{reranker.model_name} device={reranker.device}")
    return reranker.rerank


def build_retriever(
    args: argparse.Namespace,
    corpus: Optional[Dict[str, str]],
    index: Optional["IndexManifest"],
    text_lookup: Callable[[str], Optional[str]],
) -> Any:
    """按「召回 → 精排 → 折叠到段落」的顺序装配检索链路

    顺序不可颠倒：精排作用在分块上（与线上一致），折叠发生在最后（评测口径）。
    """
    from app.rag_eval import (
        HybridRetriever,
        InMemoryRetriever,
        PassageMappedRetriever,
        QdrantRetriever,
        RerankedRetriever,
    )

    if args.retriever == "in-memory":
        if not corpus:
            raise SystemExit("--retriever in-memory 需要 --corpus 指定语料文件")
        base: Any = InMemoryRetriever(corpus)
    else:
        collection = args.collection or (index.collection if index else None)
        if not collection:
            raise SystemExit("--retriever qdrant 需要 --collection，或提供 --index-dir 以从清单读取")
        if args.hybrid:
            # 混合检索必须在精排/折叠**之前**完成融合，顺序与线上一致：
            # 线上也是先融合出候选，再（可选）精排，最后才截断。
            base = HybridRetriever(
                collection_name=collection,
                alpha=args.hybrid_alpha,
                dense_k=args.hybrid_dense_k,
                sparse_k=args.hybrid_sparse_k,
            )
        else:
            base = QdrantRetriever(collection_name=collection)

    if args.rerank:
        base = RerankedRetriever(
            base=base,
            rerank_fn=build_rerank_fn(args),
            text_lookup=text_lookup,
            candidate_k=args.candidate_k,
        )

    if index is not None:
        base = PassageMappedRetriever(base, index.id_map, oversample=args.oversample)
    return base


def parse_k_values(raw: str) -> Tuple[int, ...]:
    try:
        values = tuple(sorted({int(part) for part in raw.split(",") if part.strip()}))
    except ValueError as exc:
        raise SystemExit(f"--k 解析失败：{exc}")
    if not values or values[0] < 1:
        raise SystemExit("--k 必须为正整数")
    return values


def check_index_coverage(
    args: argparse.Namespace,
    golden: "GoldenSet",
    corpus: Optional[Dict[str, str]],
    index: Optional["IndexManifest"],
) -> None:
    """校验金标准引用的检索单元是否都存在于索引中

    覆盖率不足会**人为压低 Recall 上限**，而指标本身不会暴露这一点——报告里只会
    看到「召回率低」，让人误以为是检索算法的问题。因此必须在跑分前显式告警。
    """
    pool = golden.relevant_id_pool

    if index is not None:
        indexed_passages = {chunk.passage_id for chunk in index.chunks}
        missing = [unit for unit in pool if unit not in indexed_passages]
        if missing:
            print(
                f"[warn] 金标准引用的 {len(missing)}/{len(pool)} 个段落不在索引中，"
                f"Recall 上限将被压低。示例：{missing[:3]}"
            )
        else:
            print(f"[ok] 索引覆盖率校验通过：{len(pool)} 个相关段落全部可检索")
        return

    if args.retriever == "in-memory":
        if corpus is None:
            return
        missing = [unit for unit in pool if unit not in corpus]
        if missing:
            print(
                f"[warn] 金标准引用的 {len(missing)}/{len(pool)} 个检索单元不在语料中，"
                f"Recall 上限将被压低。示例：{missing[:3]}"
            )
        else:
            print(f"[ok] 索引覆盖率校验通过：{len(pool)} 个相关单元全部可检索")
        return

    _report_qdrant_coverage(args.collection, pool)


def _report_qdrant_coverage(collection_name: Optional[str], ids: Sequence[str]) -> None:
    """用 ``has_id`` 过滤统计相关单元在 Qdrant 中的存在数量"""
    if not collection_name:
        return
    from qdrant_client.models import Filter, HasIdCondition

    from app.core.vector_db import get_qdrant_client

    try:
        found = get_qdrant_client().count(
            collection_name=collection_name,
            count_filter=Filter(must=[HasIdCondition(has_id=list(ids))]),
            exact=True,
        ).count
    except Exception as exc:  # noqa: BLE001 - 覆盖率属辅助校验，不应阻断评测
        print(f"[warn] 索引覆盖率校验失败（不影响评测继续）：{exc}")
        return

    if found == len(ids):
        print(f"[ok] 索引覆盖率校验通过：{len(ids)} 个相关单元全部可检索")
        return

    print(
        f"[warn] 索引中仅存在 {found}/{len(ids)} 个相关单元，Recall 上限将被压低。"
        "（Qdrant 只返回存在总数，逐项缺失清单由数据集构建阶段的清单比对给出）"
    )


# ── 主流程 ──────────────────────────────────────────────────────────────────


def print_summary(run: "EvalRun", gate_results: Sequence["RegressionCheck"] = ()) -> None:
    ks = run.k_values
    print()
    print(f"运行：{run.name}    检索器：{run.retriever_name}")
    print(f"查询数：{run.n_scored}（失败 {run.n_failed}）")
    print("-" * 58)
    header = f"{'指标':<10}" + "".join(f"{'@' + str(k):>12}" for k in ks)
    print(header)
    for metric in ("recall", "hit", "mrr", "ndcg", "map"):
        cells = "".join(
            f"{(run.metric(f'{metric}@{k}') or 0.0):>12.4f}" for k in ks
        )
        print(f"{metric.upper():<10}{cells}")
    if run.metric("candidate_recall") is not None:
        print(f"{'candidate':<10}{run.metric('candidate_recall'):>12.4f}  (recall)")
        print(f"{'cand.size':<10}{run.metric('candidate_size'):>12.1f}  (实际候选集规模)")
    print("-" * 58)
    retrieve = run.latency.get("retrieve") or {}
    print(f"召回延迟 p50={retrieve.get('p50')}ms  p95={retrieve.get('p95')}ms")
    rerank = run.latency.get("rerank") or {}
    if rerank:
        print(f"精排延迟 p50={rerank.get('p50')}ms  p95={rerank.get('p95')}ms")
    total = run.latency.get("total") or {}
    if total:
        print(f"端到端延迟 p50={total.get('p50')}ms  p95={total.get('p95')}ms")

    for check in gate_results:
        flag = "✅ 通过" if check.passed else "❌ 不通过"
        delta = "—" if check.delta_pp is None else f"{check.delta_pp:+.2f}pp"
        print(f"门禁 {check.metric}: {flag}  基线={check.baseline}  本次={check.current}  Δ={delta}")


def _make_progress_printer() -> Callable[[int, int, Any], None]:
    """构造逐条进度打印器（供 ``Evaluator.on_progress`` 使用）

    为什么必须有：精排评测单条耗时 30 秒以上，整轮数十分钟。中间若没有任何输出，
    一次**正常的慢跑**与一次**卡死**在外部观察上完全同形——本项目已两次因长任务
    长时间无输出而把「慢」误判为「挂起」。因此这里逐条打印进度、已用时与预计剩余，
    并强制 ``flush``：stdout 重定向到文件时是块缓冲，不 flush 则日志会长时间保持
    为空，等于没有输出。
    """
    started = time.monotonic()
    errors = 0

    def report(done: int, total: int, outcome: Any) -> None:
        nonlocal errors
        elapsed = time.monotonic() - started
        per_query = elapsed / done if done else 0.0
        eta_min = per_query * (total - done) / 60
        if outcome.error:
            errors += 1
            status = f"ERR {str(outcome.error)[:70]}"
        else:
            status = "ok"
        print(
            f"[{done}/{total}] {str(outcome.query_id):<12} {str(outcome.query_type):<8}"
            f" {status}  已用 {elapsed / 60:.1f}min  剩余≈{eta_min:.1f}min"
            f"  失败累计 {errors}",
            flush=True,
        )

    return report


def main(argv: Optional[Sequence[str]] = None) -> int:
    # 先解析参数，再导入应用模块：保证 --help 不触发配置加载（见模块 docstring）
    args = build_parser().parse_args(argv)
    k_values = parse_k_values(args.k)

    from app.rag_eval import (
        Evaluator,
        GoldenSet,
        check_regression,
        load_baseline,
        merge_runs,
        render_comparison_markdown,
        render_markdown,
        write_json,
        write_markdown,
    )

    index = load_index(args.index_dir) if args.index_dir else None
    index_dir = Path(args.index_dir) if args.index_dir else None

    golden_path = args.golden or (index_dir / "golden.jsonl" if index_dir else None)
    if not golden_path:
        raise SystemExit("需要 --golden，或提供 --index-dir 以使用其中的 golden.jsonl")
    golden = GoldenSet.load(golden_path)
    if len(golden) == 0:
        raise SystemExit(f"金标准集为空：{golden_path}")

    corpus = load_corpus(args.corpus) if args.corpus else None
    text_lookup = build_text_lookup(corpus, index)

    if index is not None:
        info = index.summary()
        print(f"[ok] 索引清单：collection={info['collection']} "
              f"段落={info['n_passages']} 分块={info['n_chunks']}")

    check_index_coverage(args, golden, corpus, index)

    name = args.name or f"{args.retriever}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    # 续跑：分组聚合必须基于**完整**金标准集，故在裁剪前保存引用
    full_golden = golden
    previous = None
    if args.resume:
        previous = load_previous_run(args.resume)
        done = {item.query_id for item in previous.outcomes if item.error is None}
        remaining = [query for query in golden.queries if query.query_id not in done]
        print(
            f"[ok] 续跑：历史成功 {len(done)} 条，本次待跑 {len(remaining)} 条"
            f"（金标准合计 {len(golden)}）"
        )
        golden = GoldenSet(queries=remaining, manifest=golden.manifest)

    if len(golden) == 0:
        assert previous is not None  # 仅 --resume 时可能为空
        run = previous
        print("[ok] 无待跑查询：直接输出历史结果")
    else:
        retriever = build_retriever(args, corpus, index, text_lookup)
        run = Evaluator(
            retriever=retriever,
            k_values=k_values,
            name=name,
            on_progress=_make_progress_printer(),
        ).run(golden)
        if previous is not None:
            run = merge_runs([previous, run], groups=full_golden.groups)
            run.name = name
            # 数据集统计必须取**完整**金标准集：merge_runs 取的是最后一次运行的
            # 元信息，而那次只跑了「待跑子集」，直接沿用会让报告声明的查询数
            # 与实际评分条数不一致。
            run.dataset_stats = full_golden.stats()
            print(
                f"[ok] 已合并历史结果：覆盖 {len(run.outcomes)} 条查询"
                f"（成功 {run.n_scored}，失败 {run.n_failed}）"
            )

    out_dir = Path(args.out_dir)
    json_path = write_json(run, out_dir / f"{name}.json")
    gate_results = []
    comparison_path = None
    if args.baseline:
        baseline = load_baseline(args.baseline)
        gate_results = [
            check_regression(
                run,
                baseline,
                metric=args.gate_metric,
                max_drop_pp=args.max_drop_pp,
            )
        ]
        # 对照报告是 Phase 4 的主要交付物，与门禁共用同一份基线，避免口径分叉。
        comparison_path = write_markdown(
            render_comparison_markdown(baseline, run, title=f"{name} vs 基线"),
            out_dir / f"{name}-comparison.md",
        )
    md_path = write_markdown(render_markdown(run, gate_results), out_dir / f"{name}.md")

    print_summary(run, gate_results)
    print()
    print(f"JSON 报告：{json_path}")
    print(f"Markdown 报告：{md_path}")
    if comparison_path:
        print(f"对照报告：{comparison_path}")

    if gate_results and not all(check.passed for check in gate_results):
        return 1 if args.fail_on_regression else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
