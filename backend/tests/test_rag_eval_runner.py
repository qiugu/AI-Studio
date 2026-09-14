"""Runner / Retriever / Report 单测

全部离线运行（不依赖 Qdrant、MySQL、模型权重），
因此可以在任意环境与 CI 中作为回归门禁执行。
"""

from pathlib import Path

import pytest

from app.rag_eval.dataset import GoldenSet, load_jsonl
from app.rag_eval.report import (
    check_regression,
    load_baseline,
    render_comparison_markdown,
    render_markdown,
    write_json,
)
from app.rag_eval.retrievers import InMemoryRetriever, RerankedRetriever, Retriever
from app.rag_eval.runner import Evaluator

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "rag_eval"


@pytest.fixture(scope="module")
def corpus() -> dict:
    return {row["id"]: row["text"] for row in load_jsonl(FIXTURE_DIR / "corpus.jsonl")}


@pytest.fixture(scope="module")
def golden() -> GoldenSet:
    return GoldenSet.load(FIXTURE_DIR / "golden.jsonl")


class TestInMemoryRetriever:
    def test_is_deterministic_across_instances(self, corpus):
        """同一语料 + 同一查询 → 逐位一致的排序（无随机数参与）"""
        first = InMemoryRetriever(corpus).retrieve("文档分块大小", top_k=5)
        second = InMemoryRetriever(corpus).retrieve("文档分块大小", top_k=5)
        assert first.ids == second.ids
        assert first.scores == second.scores

    def test_lexical_overlap_drives_ranking(self, corpus):
        """词面重叠高的单元应排第一——否则断言只能是「返回了 k 条」，失去意义"""
        result = InMemoryRetriever(corpus).retrieve("bge-base-zh-v1.5 的向量维度", top_k=3)
        assert result.top1 == "doc-004"

    def test_respects_top_k(self, corpus):
        assert len(InMemoryRetriever(corpus).retrieve("分块", top_k=3).ids) == 3

    def test_invalid_dim_rejected(self, corpus):
        with pytest.raises(ValueError, match="dim must be"):
            InMemoryRetriever(corpus, dim=0)


class TestRerankedRetriever:
    def test_rerank_reorders_and_records_candidates(self, corpus):
        """精排改变最终顺序，且保留重排前候选集用于度量召回损失"""

        def reverse_by_length(query, candidates):
            # 按原文长度倒序，制造一个与基础排序明显不同的顺序
            return sorted(
                ((doc_id, float(len(text))) for doc_id, text in candidates),
                key=lambda item: -item[1],
            )

        base = InMemoryRetriever(corpus)
        plain = base.retrieve("文档分块大小", top_k=3)
        wrapped = RerankedRetriever(
            base=base,
            rerank_fn=reverse_by_length,
            text_lookup=corpus.get,
            candidate_k=5,
        ).retrieve("文档分块大小", top_k=3)

        assert wrapped.candidate_ids is not None
        assert len(wrapped.candidate_ids) == 5
        assert wrapped.ids[0] == max(corpus, key=lambda key: len(corpus[key]))
        assert wrapped.ids != plain.ids
        assert wrapped.rerank_latency_ms is not None

    def test_unresolvable_text_is_kept_not_dropped(self, corpus):
        """候选缺原文时不得静默丢弃：丢弃会让 Recall 无故下降且难以排查"""
        base = InMemoryRetriever(corpus)
        wrapped = RerankedRetriever(
            base=base,
            rerank_fn=lambda query, candidates: [(doc_id, 1.0) for doc_id, _ in candidates],
            text_lookup=lambda _doc_id: None,  # 全部拿不到原文
            candidate_k=4,
        ).retrieve("分块", top_k=4)

        assert wrapped.ids == base.retrieve("分块", top_k=4).ids
        assert wrapped.rerank_latency_ms is not None

    def test_rerank_fn_returning_unknown_ids_is_defended(self, corpus):
        """精排返回未知/重复 id 时不得污染结果集"""
        base = InMemoryRetriever(corpus)
        wrapped = RerankedRetriever(
            base=base,
            rerank_fn=lambda query, candidates: [("ghost", 9.9), (candidates[0][0], 1.0)],
            text_lookup=corpus.get,
            candidate_k=3,
        ).retrieve("分块", top_k=3)

        assert "ghost" not in wrapped.ids
        assert len(wrapped.ids) == len(set(wrapped.ids))

    def test_invalid_candidate_k_rejected(self, corpus):
        with pytest.raises(ValueError, match="candidate_k"):
            RerankedRetriever(
                base=InMemoryRetriever(corpus),
                rerank_fn=lambda query, candidates: [],
                text_lookup=corpus.get,
                candidate_k=0,
            )


class TestEvaluator:
    def test_perfect_hit_rate_on_fixture(self, corpus, golden):
        """夹具语料下 6 条查询的首位均应命中（Hit@1 = 1.0）

        该断言同时校验了「指标聚合」与「检索器」两侧：任一侧出错都会掉下来。
        """
        run = Evaluator(InMemoryRetriever(corpus), name="fixture").run(golden)
        assert run.n_scored == 6
        assert run.n_failed == 0
        assert run.metric("hit@1") == pytest.approx(1.0)
        assert run.metric("recall@3") == pytest.approx(1.0)
        assert run.metric("mrr@1") == pytest.approx(1.0)

    def test_recall_at_1_reflects_multi_relevant_query(self, corpus, golden):
        """q-006 有 2 条相关项，@1 下最多命中 1 条 → R@1 = 5.5/6 = 11/12

        这条用例专门校验分母口径：若分母误用 top_k 内的相关项数，结果会是 1.0。
        """
        run = Evaluator(InMemoryRetriever(corpus)).run(golden)
        assert run.metric("recall@1") == pytest.approx(11 / 12)
        assert run.metric("recall@5") == pytest.approx(1.0)

    def test_candidate_recall_present_only_with_wide_candidates(self, corpus, golden):
        """只有宽召回检索器才产出 candidate_recall，用于分离召回损失与排序损失"""
        plain = Evaluator(InMemoryRetriever(corpus)).run(golden)
        assert plain.metric("candidate_recall") is None

        wrapped = RerankedRetriever(
            base=InMemoryRetriever(corpus),
            rerank_fn=lambda query, candidates: [(doc_id, 1.0) for doc_id, _ in candidates],
            text_lookup=corpus.get,
            candidate_k=6,
        )
        # k 最大值 5 < candidate_k 6，故候选集规模为 6（若 k 更大则至少取到 k 条，
        # 否则 recall@k 根本无法计算）
        reranked = Evaluator(wrapped, k_values=[1, 3, 5]).run(golden)
        assert reranked.metric("candidate_recall") is not None
        assert reranked.metric("candidate_size") == 6.0

    def test_by_query_type_mrr_is_not_empty(self, corpus, golden):
        """回归防护：mrr@k 是派生指标，分类型聚合必须回落到 rr@k 取数

        早期实现里分类型表的 mrr 整列为空（单查询指标字典中无 mrr@k 键）。
        """
        run = Evaluator(InMemoryRetriever(corpus)).run(golden)
        for type_name, metrics in run.by_query_type.items():
            assert metrics.get("mrr@5") is not None, f"{type_name} 的 mrr@5 缺失"
        assert run.type_counts == {"exact_term": 1, "fact": 2, "multi_doc": 1, "paraphrase": 2}

    def test_latency_recorded(self, corpus, golden):
        run = Evaluator(InMemoryRetriever(corpus)).run(golden)
        assert run.latency["retrieve"]["p50"] is not None
        assert run.latency["total"]["p95"] is not None

    def test_failing_retriever_is_isolated_and_counted(self, golden):
        """单条查询失败不得中断整轮评测，且必须计入 n_failed 并保留错误信息"""

        class ExplodingRetriever(Retriever):
            name = "exploding"

            def retrieve(self, query, top_k):
                raise RuntimeError("qdrant unavailable")

        run = Evaluator(ExplodingRetriever()).run(golden)
        assert run.n_failed == 6
        assert run.n_scored == 0
        assert run.outcomes[0].error.startswith("RuntimeError")
        assert run.aggregate == {}

    def test_progress_callback_reports_every_query(self, corpus, golden):
        """逐条进度必须完整上报——长任务的心跳依赖它

        精排单轮数十分钟，若进度缺条或只报总数，外部无法判断「在跑」还是「卡死」。
        这里同时校验条数、total 口径与顺序，确保回调与 outcomes 一一对应。
        """
        seen = []
        run = Evaluator(
            InMemoryRetriever(corpus),
            name="progress",
            on_progress=lambda done, total, outcome: seen.append(
                (done, total, outcome.query_id)
            ),
        ).run(golden)

        assert [item[0] for item in seen] == list(range(1, len(golden) + 1))
        assert {item[1] for item in seen} == {len(golden)}
        assert [item[2] for item in seen] == [outcome.query_id for outcome in run.outcomes]

    def test_progress_callback_failure_does_not_abort_run(self, corpus, golden):
        """回调抛错不得影响评测：进度是观测手段，不是被测对象

        且失败后应被摘除（只尝试一次），而不是每条查询都重复抛同一异常。
        """
        calls = []

        def broken(done, total, outcome):
            calls.append(done)
            raise RuntimeError("log pipe closed")

        run = Evaluator(
            InMemoryRetriever(corpus), name="broken-progress", on_progress=broken
        ).run(golden)

        assert run.n_scored == 6
        assert len(calls) == 1

    def test_invalid_k_values_rejected(self, corpus):
        with pytest.raises(ValueError, match="positive integers"):
            Evaluator(InMemoryRetriever(corpus), k_values=[0])

    def test_to_dict_is_json_serialisable(self, corpus, golden):
        import json

        run = Evaluator(InMemoryRetriever(corpus)).run(golden)
        payload = json.dumps(run.to_dict(), ensure_ascii=False)
        assert "recall@5" in payload


class TestReport:
    def test_markdown_contains_all_sections(self, corpus, golden):
        run = Evaluator(InMemoryRetriever(corpus), name="rep").run(golden)
        markdown = render_markdown(run)
        for heading in (
            "# 检索评测报告 — rep",
            "## 总体指标",
            "## 分查询类型指标",
            "## 延迟",
            "## 数据集与可复现性",
        ):
            assert heading in markdown
        assert "—" not in markdown.split("## 分查询类型指标")[1].split("##")[0]

    def test_write_json_then_load_baseline_round_trip(self, corpus, golden, tmp_path):
        run = Evaluator(InMemoryRetriever(corpus), name="base").run(golden)
        path = write_json(run, tmp_path / "base.json")
        baseline = load_baseline(path)
        assert baseline["aggregate"]["recall@5"] == pytest.approx(1.0)

    def test_comparison_markdown_shows_delta(self, corpus, golden, tmp_path):
        baseline_run = Evaluator(InMemoryRetriever(corpus), name="before").run(golden)
        baseline = load_baseline(write_json(baseline_run, tmp_path / "before.json"))

        class WorseRetriever(Retriever):
            name = "worse"

            def retrieve(self, query, top_k):
                result = InMemoryRetriever(corpus).retrieve(query, top_k)
                result.ids = list(reversed(result.ids))
                return result

        current = Evaluator(WorseRetriever(), name="after").run(golden)
        markdown = render_comparison_markdown(baseline, current)
        assert "| `recall@5` |" in markdown
        assert "↓" in markdown


class TestRegressionGate:
    @staticmethod
    def _baseline(value: float, metric: str = "recall@5") -> dict:
        return {"name": "base", "aggregate": {metric: value}}

    def test_pass_within_threshold(self, corpus, golden):
        run = Evaluator(InMemoryRetriever(corpus)).run(golden)
        check = check_regression(run, self._baseline(0.999), "recall@5", max_drop_pp=1.0)
        assert check.passed
        assert check.delta_pp == pytest.approx(0.1, abs=0.01)

    def test_fail_when_drop_exceeds_threshold(self, corpus, golden):
        run = Evaluator(InMemoryRetriever(corpus)).run(golden)
        check = check_regression(
            run, self._baseline(1.0, "recall@1"), "recall@1", max_drop_pp=1.0
        )
        assert not check.passed
        # 1.0 → 11/12 即下降 8.33pp
        assert check.delta_pp == pytest.approx(-8.3333, abs=0.01)

    def test_improvement_passes(self, corpus, golden):
        run = Evaluator(InMemoryRetriever(corpus)).run(golden)
        assert check_regression(run, self._baseline(0.5), "recall@5").passed

    def test_missing_baseline_metric_does_not_pass(self, corpus, golden):
        """缺失 ≠ 通过：无法验证时必须判定不通过，否则门禁在数据不全时静默失效"""
        run = Evaluator(InMemoryRetriever(corpus)).run(golden)
        check = check_regression(run, {"aggregate": {}}, "recall@5")
        assert not check.passed
        assert "不存在" in check.note

    def test_missing_current_metric_does_not_pass(self, corpus, golden):
        """基线有、本次无 → 同样不能判定通过"""
        run = Evaluator(InMemoryRetriever(corpus)).run(golden)
        check = check_regression(run, {"aggregate": {"recall@99": 0.5}}, "recall@99")
        assert not check.passed
        assert "未产出" in check.note
