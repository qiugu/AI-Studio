"""评测编排：金标准 → 召回 → 指标 → 聚合

一次评测运行（``EvalRun``）应当自证其可复现性，因此除指标本身外还需固化：

* 数据集统计与采样清单（``manifest``）——说明结论是基于哪一份语料得出的；
* 分阶段延迟——质量提升若以不可接受的延迟为代价，结论就没有落地价值；
* 分类型指标——只看总体均值会掩盖「某类查询变好、另一类变坏」的结构性变化。

**召回损失 vs 排序损失**：当检索器提供宽召回候选集（``candidate_ids``）时，
同时计算 ``candidate_recall``（候选集内的召回率）与 ``recall@k``。两者的差额
就是纯粹由排序造成的损失——这是判断「该补召回还是该上精排」的唯一依据。
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

from app.rag_eval.dataset import GoldenQuery, GoldenSet
from app.rag_eval.metrics import (
    DEFAULT_KS,
    average_precision_at_k,
    hit_at_k,
    macro_average,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank_at_k,
    summarize_by_key,
)
from app.rag_eval.retrievers import RetrievalResult, Retriever

__all__ = ["QueryOutcome", "EvalRun", "Evaluator", "merge_runs"]


@dataclass
class QueryOutcome:
    """单查询评测结果"""

    query_id: str
    query_type: str
    n_relevant: int
    retrieved_ids: List[str]
    candidate_ids: Optional[List[str]]
    metrics: Dict[str, Optional[float]] = field(default_factory=dict)
    retrieve_latency_ms: float = 0.0
    rerank_latency_ms: Optional[float] = None
    error: Optional[str] = None

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "QueryOutcome":
        """从报告 JSON 的 ``per_query`` 条目还原

        用途是**中断后续跑**：长任务（精排尤其）可能因外部原因中断，历史结果必须
        能被读回并复用，否则每次中断都要从头重算。因此除 ``query_id`` 外全部字段
        都按「缺失即默认」处理——报告格式演进不应让旧报告变得不可读。
        """
        candidate_ids = payload.get("candidate_ids")
        rerank_latency = payload.get("rerank_latency_ms")
        return cls(
            query_id=str(payload["query_id"]),
            query_type=str(payload.get("query_type") or "unknown"),
            n_relevant=int(payload.get("n_relevant") or 0),
            retrieved_ids=[str(item) for item in payload.get("retrieved_ids") or []],
            candidate_ids=(
                [str(item) for item in candidate_ids] if candidate_ids else None
            ),
            metrics=dict(payload.get("metrics") or {}),
            retrieve_latency_ms=float(payload.get("retrieve_latency_ms") or 0.0),
            rerank_latency_ms=(
                float(rerank_latency) if rerank_latency is not None else None
            ),
            error=payload.get("error"),
        )

    def to_dict(self) -> Dict[str, Any]:
        """转为报告 JSON 的 ``per_query`` 条目（与 :meth:`EvalRun.to_dict` 同构）"""
        return {
            "query_id": self.query_id,
            "query_type": self.query_type,
            "n_relevant": self.n_relevant,
            "retrieved_ids": list(self.retrieved_ids),
            "candidate_ids": list(self.candidate_ids) if self.candidate_ids else None,
            "metrics": dict(self.metrics),
            "retrieve_latency_ms": round(self.retrieve_latency_ms, 3),
            "rerank_latency_ms": (
                round(self.rerank_latency_ms, 3)
                if self.rerank_latency_ms is not None
                else None
            ),
            "error": self.error,
        }


@dataclass
class EvalRun:
    """一次完整评测运行的产物"""

    name: str
    k_values: Tuple[int, ...]
    retriever_name: str
    outcomes: List[QueryOutcome]
    aggregate: Dict[str, Optional[float]]
    by_query_type: Dict[str, Dict[str, Optional[float]]]
    latency: Dict[str, Optional[float]]
    n_scored: int
    n_failed: int
    dataset_stats: Dict[str, Any]
    type_counts: Dict[str, int] = field(default_factory=dict)
    manifest: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """转为可 JSON 序列化的结构（报告与回归基线的统一格式）"""
        return {
            "name": self.name,
            "retriever": self.retriever_name,
            "k_values": list(self.k_values),
            "n_scored": self.n_scored,
            "n_failed": self.n_failed,
            "aggregate": self.aggregate,
            "by_query_type": self.by_query_type,
            "type_counts": self.type_counts,
            "latency_ms": self.latency,
            "dataset": self.dataset_stats,
            "manifest": self.manifest,
            "per_query": [
                {
                    "query_id": outcome.query_id,
                    "query_type": outcome.query_type,
                    "n_relevant": outcome.n_relevant,
                    "retrieved_ids": outcome.retrieved_ids,
                    "metrics": outcome.metrics,
                    "retrieve_latency_ms": round(outcome.retrieve_latency_ms, 3),
                    "rerank_latency_ms": (
                        round(outcome.rerank_latency_ms, 3)
                        if outcome.rerank_latency_ms is not None
                        else None
                    ),
                    "error": outcome.error,
                }
                for outcome in self.outcomes
            ],
        }

    def metric(self, key: str) -> Optional[float]:
        """取聚合指标，如 ``run.metric("recall@5")``"""
        return self.aggregate.get(key)

    @classmethod
    def from_report(cls, payload: Dict[str, Any]) -> "EvalRun":
        """从 :meth:`to_dict` 产出的报告 JSON 还原（用于中断后续跑的合并）

        除 ``per_query`` 外全部按「缺失即默认」处理，使旧版本报告仍可读。
        """
        return cls(
            name=str(payload.get("name") or "restored"),
            k_values=tuple(int(k) for k in (payload.get("k_values") or DEFAULT_KS)),
            retriever_name=str(payload.get("retriever") or "unknown"),
            outcomes=[
                QueryOutcome.from_dict(item) for item in payload.get("per_query") or []
            ],
            aggregate=dict(payload.get("aggregate") or {}),
            by_query_type=dict(payload.get("by_query_type") or {}),
            type_counts=dict(payload.get("type_counts") or {}),
            latency=dict(payload.get("latency_ms") or {}),
            n_scored=int(payload.get("n_scored") or 0),
            n_failed=int(payload.get("n_failed") or 0),
            dataset_stats=dict(payload.get("dataset") or {}),
            manifest=payload.get("manifest"),
        )


class Evaluator:
    """驱动检索器跑完整个金标准集，并聚合指标

    Args:
        retriever: 任何 :class:`~app.rag_eval.retrievers.Retriever` 实现
        k_values: 计算截断指标的 k 列表
        name: 本次运行的标识（写入报告，用于 before/after 对照）
        on_progress: 每完成一条查询回调 ``(已完成数, 总数, 结果)``。精排评测单轮
            可达数十分钟，调用方需要据此输出心跳——否则「跑得慢」与「卡死了」在
            外部观察上完全同形。
    """

    def __init__(
        self,
        retriever: Retriever,
        k_values: Sequence[int] = DEFAULT_KS,
        name: Optional[str] = None,
        on_progress: Optional[Callable[[int, int, QueryOutcome], None]] = None,
    ) -> None:
        ks = tuple(sorted({int(k) for k in k_values}))
        if not ks or ks[0] < 1:
            raise ValueError("k_values must contain positive integers")
        self.retriever = retriever
        self.k_values = ks
        self.name = name or retriever.name
        self.on_progress = on_progress

    # ── 主流程 ──────────────────────────────────────────────────────────────

    def run(self, golden: GoldenSet) -> EvalRun:
        outcomes: List[QueryOutcome] = []

        for query in golden.queries:
            try:
                result = self.retriever.retrieve(query.query, top_k=max(self.k_values))
                outcomes.append(self._score(query, result))
            except Exception as exc:  # noqa: BLE001 - 单条失败不应中止整轮评测
                # 评测必须跑完：一条查询失败就中断会让「部分失败」伪装成「未运行」，
                # 而失败条数会被显式计入 n_failed 并在报告中披露。
                outcomes.append(
                    QueryOutcome(
                        query_id=query.query_id,
                        query_type=query.query_type or "unknown",
                        n_relevant=len(query.relevant),
                        retrieved_ids=[],
                        candidate_ids=None,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )
            self._notify_progress(len(outcomes), len(golden), outcomes[-1])

        scored = [outcome for outcome in outcomes if outcome.error is None]
        aggregate = self._aggregate(scored)

        # 分类型聚合：注意 `mrr@k` 是 `rr@k` 的派生指标，单查询指标字典中并不存在
        # 该键，必须回落到 `rr@k` 取数，否则分组结果会整列显示为空。
        by_type = self._aggregate_by_type(scored, aggregate, golden.groups)

        type_counts: Dict[str, int] = {}
        for outcome in scored:
            type_counts[outcome.query_type] = type_counts.get(outcome.query_type, 0) + 1

        return EvalRun(
            name=self.name,
            k_values=self.k_values,
            retriever_name=self.retriever.name,
            outcomes=outcomes,
            aggregate=aggregate,
            by_query_type=dict(sorted(by_type.items())),
            type_counts=dict(sorted(type_counts.items())),
            latency=self._latency(scored),
            n_scored=len(scored),
            n_failed=len(outcomes) - len(scored),
            dataset_stats=golden.stats(),
            manifest=golden.manifest,
        )

    def _notify_progress(self, done: int, total: int, outcome: QueryOutcome) -> None:
        """调用进度回调；回调自身的异常不得影响评测

        进度输出是**观测手段**而非评测结果。若调用方的打印抛错（如输出管道已关闭），
        让一轮数十分钟的评测因此作废是不可接受的取舍。失败后即摘除回调，避免每条
        查询都重复触发同一异常。
        """
        if self.on_progress is None:
            return
        try:
            self.on_progress(done, total, outcome)
        except Exception:  # noqa: BLE001 - 观测失败不阻断评测
            self.on_progress = None

    # ── 单查询打分 ──────────────────────────────────────────────────────────

    def _score(self, query: GoldenQuery, result: RetrievalResult) -> QueryOutcome:
        relevant_ids = query.relevant_ids
        gains = query.gains
        metrics: Dict[str, Optional[float]] = {}

        for k in self.k_values:
            metrics[f"recall@{k}"] = recall_at_k(result.ids, relevant_ids, k)
            metrics[f"hit@{k}"] = hit_at_k(result.ids, relevant_ids, k)
            metrics[f"precision@{k}"] = precision_at_k(result.ids, relevant_ids, k)
            metrics[f"rr@{k}"] = reciprocal_rank_at_k(result.ids, relevant_ids, k)
            metrics[f"map@{k}"] = average_precision_at_k(result.ids, relevant_ids, k)
            metrics[f"ndcg@{k}"] = ndcg_at_k(result.ids, gains, k)

        if result.candidate_ids:
            # 候选集规模即宽召回的 k，用它度量「召回上限」，与最终 recall@k 相减即排序损失
            candidate_size = len(result.candidate_ids)
            metrics["candidate_size"] = float(candidate_size)
            metrics["candidate_recall"] = recall_at_k(
                result.candidate_ids, relevant_ids, candidate_size
            )

        return QueryOutcome(
            query_id=query.query_id,
            query_type=query.query_type or "unknown",
            n_relevant=len(query.relevant),
            retrieved_ids=list(result.ids),
            candidate_ids=list(result.candidate_ids) if result.candidate_ids else None,
            metrics=metrics,
            retrieve_latency_ms=result.retrieve_latency_ms,
            rerank_latency_ms=result.rerank_latency_ms,
        )

    # ── 聚合 ────────────────────────────────────────────────────────────────

    @staticmethod
    def _aggregate_by_type(
        scored: Sequence[QueryOutcome],
        aggregate: Dict[str, Optional[float]],
        groups: Dict[str, str],
    ) -> Dict[str, Dict[str, Optional[float]]]:
        """按查询类型重算指标（``run`` 与 :func:`merge_runs` 共用，避免口径分叉）

        注意 ``mrr@k`` 是 ``rr@k`` 的派生键，单查询指标字典中不存在该键，必须回落到
        ``rr@k`` 取数，否则分组结果会整列显示为空。
        """
        by_type: Dict[str, Dict[str, Optional[float]]] = {}
        for metric_key in aggregate:
            source_key = (
                f"rr@{metric_key.split('@', 1)[1]}" if metric_key.startswith("mrr@") else metric_key
            )
            per_query_values = {
                outcome.query_id: outcome.metrics.get(source_key) for outcome in scored
            }
            for type_name, value in summarize_by_key(per_query_values, groups).items():
                by_type.setdefault(type_name, {})[metric_key] = value
        return dict(sorted(by_type.items()))

    @staticmethod
    def _aggregate(scored: Sequence[QueryOutcome]) -> Dict[str, Optional[float]]:
        """宏观平均（单查询等权）；同时派生 ``mrr@k`` = ``rr@k`` 的宏观平均"""
        if not scored:
            return {}

        keys: List[str] = []
        for outcome in scored:
            for key in outcome.metrics:
                if key not in keys:
                    keys.append(key)

        aggregate: Dict[str, Optional[float]] = {}
        for key in keys:
            values = [outcome.metrics.get(key) for outcome in scored]
            aggregate[key] = macro_average(values)
            if key.startswith("rr@"):
                aggregate[f"mrr@{key.split('@', 1)[1]}"] = aggregate[key]
        return dict(sorted(aggregate.items()))

    @staticmethod
    def _latency(scored: Sequence[QueryOutcome]) -> Dict[str, Optional[float]]:
        """分阶段延迟分位数（p50/p95，单位毫秒）"""

        def percentiles(values: Sequence[float]) -> Dict[str, Optional[float]]:
            if not values:
                return {"p50": None, "p95": None, "mean": None}
            return {
                "p50": round(float(np.percentile(values, 50)), 3),
                "p95": round(float(np.percentile(values, 95)), 3),
                "mean": round(statistics.fmean(values), 3),
            }

        retrieve = [o.retrieve_latency_ms for o in scored]
        latency = {"retrieve": percentiles(retrieve)}

        rerank = [o.rerank_latency_ms for o in scored if o.rerank_latency_ms is not None]
        if rerank:
            latency["rerank"] = percentiles(rerank)

        total = [
            o.retrieve_latency_ms + (o.rerank_latency_ms or 0.0)
            for o in scored
        ]
        latency["total"] = percentiles(total)
        return latency


def merge_runs(
    runs: Sequence[EvalRun],
    groups: Optional[Dict[str, str]] = None,
) -> EvalRun:
    """把多次运行合并为一次逻辑运行（用于长任务中断后续跑）

    为什么需要：精排评测单次数十分钟，中途可能因外部原因中断（宿主机资源回收、
    依赖服务重启等）。若每次都从头重算，已付出的算力全部作废，且产物永远无法满足
    「全部查询、同一口径」这一硬性要求。合并后仅**缺什么补什么**，最终仍是一份
    覆盖全部查询的完整报告。

    Args:
        runs: 按时间先后排列的多次运行；同一 ``query_id`` 以**后者**为准
            （后跑的即重跑了该查询）
        groups: ``query_id -> 查询类型``（取金标准集的 ``groups``）。提供时重算
            分类型指标；缺省则沿用最后一次运行的分组结果

    Returns:
        合并后的 :class:`EvalRun`：元信息（名称 / retriever / 数据集统计 / manifest）
        取最后一次运行，而指标由合并后的逐查询结果**重新计算**——不能直接把两次
        运行的 aggregate 相加或平均，因为每次运行覆盖的查询集合不同。
    """
    if not runs:
        raise ValueError("runs must be non-empty")

    # 按 query_id 去重，后写入者覆盖先写入者
    ordered: Dict[str, QueryOutcome] = {}
    for run in runs:
        for outcome in run.outcomes:
            ordered[outcome.query_id] = outcome
    outcomes = list(ordered.values())

    scored = [outcome for outcome in outcomes if outcome.error is None]
    aggregate = Evaluator._aggregate(scored)
    last = runs[-1]

    by_type = (
        Evaluator._aggregate_by_type(scored, aggregate, groups)
        if groups is not None
        else last.by_query_type
    )

    type_counts: Dict[str, int] = {}
    for outcome in scored:
        type_counts[outcome.query_type] = type_counts.get(outcome.query_type, 0) + 1

    return EvalRun(
        name=last.name,
        k_values=last.k_values,
        retriever_name=last.retriever_name,
        outcomes=outcomes,
        aggregate=aggregate,
        by_query_type=by_type,
        type_counts=dict(sorted(type_counts.items())),
        latency=Evaluator._latency(scored),
        n_scored=len(scored),
        n_failed=len(outcomes) - len(scored),
        dataset_stats=last.dataset_stats,
        manifest=last.manifest,
    )
