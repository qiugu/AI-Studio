"""评测「中断续跑」合并逻辑的单测

为什么需要这一层
----------------

精排评测单次数十分钟（实测 100 查询 × 100 候选约 31 分钟）。这类长任务会被
外部原因打断——宿主机资源回收、依赖服务重启等。若每次中断都从头重算：

1. 已付出的算力全部作废；
2. 产物永远无法覆盖「全部查询」，而**与基线同口径**是评测结论成立的前提。

因此引入 ``--resume``：保留已成功的查询结果，只补跑缺失部分，再合并。
本文件验证合并的两条核心不变量：

* **同一 query_id 后跑者胜**（后跑的即重跑了该查询）；
* **指标必须按合并后的逐查询结果重算**，不能对两次运行的 aggregate 取平均
  ——两次运行覆盖的查询集合不同，平均会产生一个既非 A 也非 B 的错误数字。
"""

from __future__ import annotations

import pytest

from app.rag_eval.dataset import GoldenQuery, GoldenSet
from app.rag_eval.retrievers import RetrievalResult
from app.rag_eval.runner import EvalRun, Evaluator, QueryOutcome, merge_runs

K_VALUES = (1, 2)


class StubRetriever:
    """按预设映射返回命中列表（顺序即排名）"""

    name = "stub"

    def __init__(self, mapping: dict[str, list[str]]) -> None:
        self._mapping = mapping

    def retrieve(self, query: str, top_k: int) -> RetrievalResult:
        ids = list(self._mapping.get(query, []))[:top_k]
        return RetrievalResult(ids=ids, scores=[1.0 - index * 0.01 for index in range(len(ids))])


def make_query(query_id: str, relevant_id: str, query_type: str = "fact") -> GoldenQuery:
    return GoldenQuery.model_validate(
        {
            "query_id": query_id,
            "query": f"问题-{query_id}",
            "relevant": [{"id": relevant_id}],
            "query_type": query_type,
        }
    )


def run_subset(mapping: dict[str, list[str]], queries: list[GoldenQuery], name: str) -> EvalRun:
    golden = GoldenSet(queries=queries)
    return Evaluator(
        retriever=StubRetriever(mapping), k_values=K_VALUES, name=name
    ).run(golden)


# ── 合并：集合语义 ──────────────────────────────────────────────────────────


def test_merge_unions_disjoint_runs() -> None:
    """两次运行查询集合不相交时，合并后应覆盖全部查询"""
    first = run_subset({"问题-q1": ["d1", "d2"]}, [make_query("q1", "d1")], "run-1")
    second = run_subset({"问题-q2": ["d2"]}, [make_query("q2", "d2")], "run-2")

    merged = merge_runs([first, second])

    assert {item.query_id for item in merged.outcomes} == {"q1", "q2"}
    assert merged.n_scored == 2
    assert merged.n_failed == 0
    # 元信息取最后一次运行
    assert merged.name == "run-2"


def test_merge_recomputes_aggregate_instead_of_averaging() -> None:
    """指标必须按逐查询结果重算，而不是对两次运行的聚合值取平均

    构造：run-1 的 recall@1 = 0.5（q1 命中、q2 未命中），run-2 的 recall@1 = 1.0。
    简单平均会得到 0.75；正确结果是 (1 + 0 + 1) / 3 = 0.6667。两者不等，
    因此该断言能真正区分「重算」与「平均」两种实现。
    """
    first = run_subset(
        {"问题-q1": ["d1", "d2"], "问题-q2": ["d1", "d2"]},
        [make_query("q1", "d1"), make_query("q2", "d2")],
        "run-1",
    )
    second = run_subset({"问题-q3": ["d3"]}, [make_query("q3", "d3")], "run-2")

    assert first.metric("recall@1") == pytest.approx(0.5)
    assert second.metric("recall@1") == pytest.approx(1.0)

    merged = merge_runs([first, second])

    assert merged.metric("recall@1") == pytest.approx(2 / 3)
    assert merged.metric("recall@1") != pytest.approx((0.5 + 1.0) / 2)


def test_merge_later_run_wins_on_same_query_id() -> None:
    """同一 query_id 以最后一次运行为准（后跑的即重跑了该查询）"""
    failed = EvalRun(
        name="failed",
        k_values=K_VALUES,
        retriever_name="stub",
        outcomes=[
            QueryOutcome(
                query_id="q1",
                query_type="fact",
                n_relevant=1,
                retrieved_ids=[],
                candidate_ids=None,
                error="ConnectionError: boom",
            )
        ],
        aggregate={},
        by_query_type={},
        latency={},
        n_scored=0,
        n_failed=1,
        dataset_stats={},
    )
    retried = run_subset({"问题-q1": ["d1"]}, [make_query("q1", "d1")], "retried")

    merged = merge_runs([failed, retried])

    assert merged.n_scored == 1
    assert merged.n_failed == 0
    assert merged.metric("recall@1") == pytest.approx(1.0)
    assert merged.outcomes[0].error is None


def test_merge_recomputes_by_query_type_when_groups_given() -> None:
    """提供 groups 时重算分类型指标；否则沿用最后一次运行的分组结果"""
    first = run_subset({"问题-q1": ["d1"]}, [make_query("q1", "d1", "exact")], "run-1")
    second = run_subset({"问题-q2": ["d1"]}, [make_query("q2", "d2", "multi")], "run-2")

    merged = merge_runs([first, second], groups={"q1": "exact", "q2": "multi"})

    assert set(merged.by_query_type) == {"exact", "multi"}
    assert merged.by_query_type["exact"]["recall@1"] == pytest.approx(1.0)
    assert merged.by_query_type["multi"]["recall@1"] == pytest.approx(0.0)


def test_merge_excludes_failed_queries_from_metrics_but_counts_them() -> None:
    """失败查询计入 n_failed，且不参与指标计算"""
    golden = GoldenSet(queries=[make_query("q1", "d1")])
    run = Evaluator(
        retriever=_BoomRetriever(), k_values=K_VALUES, name="boom"
    ).run(golden)

    assert run.n_failed == 1
    merged = merge_runs([run])

    assert merged.n_failed == 1
    assert merged.n_scored == 0
    assert merged.aggregate == {}


def test_merge_requires_at_least_one_run() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        merge_runs([])


class _BoomRetriever:
    name = "boom"

    def retrieve(self, query: str, top_k: int) -> RetrievalResult:
        raise ConnectionError("boom")


# ── 序列化：报告 JSON 往返 ──────────────────────────────────────────────────


def test_query_outcome_round_trip() -> None:
    outcome = QueryOutcome(
        query_id="q1",
        query_type="fact",
        n_relevant=2,
        retrieved_ids=["d1", "d2"],
        candidate_ids=["d1", "d2", "d3"],
        metrics={"recall@1": 0.5},
        retrieve_latency_ms=12.346,
        rerank_latency_ms=678.9,
    )

    restored = QueryOutcome.from_dict(outcome.to_dict())

    assert restored == outcome


def test_query_outcome_from_dict_tolerates_missing_optional_fields() -> None:
    """旧报告缺少 candidate_ids / rerank_latency_ms 时应可读，而不是让合并失败"""
    restored = QueryOutcome.from_dict({"query_id": "q1"})

    assert restored.query_id == "q1"
    assert restored.query_type == "unknown"
    assert restored.retrieved_ids == []
    assert restored.candidate_ids is None
    assert restored.rerank_latency_ms is None


def test_eval_run_report_round_trip() -> None:
    run = run_subset(
        {"问题-q1": ["d1", "d2"], "问题-q2": ["d2", "d1"]},
        [make_query("q1", "d1"), make_query("q2", "d2")],
        "round-trip",
    )

    restored = EvalRun.from_report(run.to_dict())

    assert restored.name == run.name
    assert restored.k_values == run.k_values
    assert restored.n_scored == run.n_scored
    assert restored.aggregate == run.aggregate
    assert [item.query_id for item in restored.outcomes] == [
        item.query_id for item in run.outcomes
    ]
    # 还原后再次合并，指标不应发生变化
    assert merge_runs([restored]).metric("recall@1") == pytest.approx(
        run.metric("recall@1")
    )
