"""CrossEncoder 精排器单测

**不加载真实权重**：精排模型约 2 GB，把它拖进单测会让测试从秒级变成分钟级，
并让 CI 依赖网络与磁盘缓存。这里通过注入 ``encoder`` 替身验证**排序契约**——
分数降序、同分稳定、结果一一对应、异常必降级；模型本身的排序质量由评测集回答
（见 Phase 4 报告），而不是单测。
"""

from __future__ import annotations

import logging
import math

import pytest

from app.utils.reranker import (
    CrossEncoderReranker,
    RerankerUnavailable,
    get_reranker,
    reset_reranker_cache,
)


class FakeEncoder:
    """可编程的 encoder 替身

    ``scorer`` 决定每个 ``(query, passage)`` 对子的分数，用以构造排序、同分、
    NaN 等边界场景；``calls`` 记录实际传入的输入，用于断言预处理行为。
    """

    def __init__(self, scorer=None):
        self.scorer = scorer or (lambda _query, passage: float(len(passage)))
        self.calls = []

    def predict(self, sentences, **kwargs):
        self.calls.append(list(sentences))
        return [self.scorer(query, passage) for query, passage in sentences]


def _reranker(scorer=None, **kwargs) -> CrossEncoderReranker:
    return CrossEncoderReranker(
        model_name="fake/reranker",
        device="cpu",
        batch_size=4,
        encoder=FakeEncoder(scorer),
        **kwargs,
    )


class TestRankingContract:
    def test_orders_by_descending_score(self):
        reranker = _reranker(lambda _q, passage: float(len(passage)))
        result = reranker.rerank("q", [("a", "xx"), ("b", "xxxx"), ("c", "xxx")])

        assert [doc_id for doc_id, _ in result] == ["b", "c", "a"]
        assert [round(score, 3) for _, score in result] == [4.0, 3.0, 2.0]

    def test_ties_preserve_original_order(self):
        """同分必须保持候选原顺序：否则同一输入可能得到不同排序，评测无法复现"""
        reranker = _reranker(lambda _q, _p: 1.0)
        result = reranker.rerank("q", [("a", "x"), ("b", "y"), ("c", "z")])

        assert [doc_id for doc_id, _ in result] == ["a", "b", "c"]

    def test_returns_every_candidate_exactly_once(self):
        """精排不得丢弃候选：静默丢弃会让 Recall 无故下降且极难排查"""
        reranker = _reranker()
        candidates = [("a", "1"), ("b", "22"), ("c", "333"), ("d", "4444")]
        result = reranker.rerank("q", candidates)

        assert len(result) == len(candidates)
        assert {doc_id for doc_id, _ in result} == {doc_id for doc_id, _ in candidates}

    def test_empty_inputs(self):
        reranker = _reranker()
        assert reranker.rerank("q", []) == []
        assert reranker.score("q", []) == []

    def test_nan_scores_are_coerced_and_order_stays_deterministic(self):
        """NaN 参与比较时排序结果未定义，必须显式压到最低分"""
        scores = {"a": 1.0, "b": float("nan"), "c": 0.5}
        reranker = _reranker(lambda _q, passage: scores[passage])
        result = reranker.rerank("q", [("a", "a"), ("b", "b"), ("c", "c")])

        assert [doc_id for doc_id, _ in result] == ["a", "c", "b"]
        assert result[-1][1] == float("-inf")


class TestPreprocessing:
    def test_trims_query_and_clips_passage(self):
        """超长文本在进入 tokenizer 前就被截断，避免无意义的内存占用"""
        from app.utils.reranker import _MAX_TEXT_CHARS

        reranker = _reranker()
        reranker.score("  hello  ", ["x" * (_MAX_TEXT_CHARS + 500)])

        query, passage = reranker._encoder.calls[0][0]
        assert query == "hello"
        assert len(passage) == _MAX_TEXT_CHARS

    def test_none_passage_becomes_empty_string(self):
        reranker = _reranker()
        reranker.score("q", [None])
        assert reranker._encoder.calls[0][0][1] == ""


class TestFailureDegradation:
    def test_load_failure_raises_unavailable(self, monkeypatch):
        import sentence_transformers

        def _explode(*_args, **_kwargs):
            raise OSError("weights not found")

        monkeypatch.setattr(sentence_transformers, "CrossEncoder", _explode)
        reranker = CrossEncoderReranker(model_name="fake/reranker")

        with pytest.raises(RerankerUnavailable, match="failed to load"):
            reranker.rerank("q", [("a", "x")])
        assert reranker.load_error is not None

    def test_load_failure_is_memoized(self, monkeypatch):
        """加载失败不会自愈，重试只会把故障成本乘以请求数"""
        import sentence_transformers

        attempts = []

        def _explode(*_args, **_kwargs):
            attempts.append(1)
            raise OSError("weights not found")

        monkeypatch.setattr(sentence_transformers, "CrossEncoder", _explode)
        reranker = CrossEncoderReranker(model_name="fake/reranker")

        for _ in range(3):
            with pytest.raises(RerankerUnavailable):
                reranker.rerank("q", [("a", "x")])
        assert len(attempts) == 1

    def test_inference_failure_raises_unavailable(self):
        class Broken:
            def predict(self, *_args, **_kwargs):
                raise RuntimeError("device exploded")

        reranker = CrossEncoderReranker(model_name="fake/reranker", encoder=Broken())
        with pytest.raises(RerankerUnavailable, match="inference failed"):
            reranker.rerank("q", [("a", "x")])

    def test_score_count_mismatch_raises(self):
        class Mismatched:
            def predict(self, sentences, **_kwargs):
                return [1.0] * (len(sentences) + 1)

        reranker = CrossEncoderReranker(model_name="fake/reranker", encoder=Mismatched())
        with pytest.raises(RerankerUnavailable, match="scores for"):
            reranker.rerank("q", [("a", "x"), ("b", "y")])

    def test_warmup_surfaces_load_error(self, monkeypatch):
        import sentence_transformers

        monkeypatch.setattr(
            sentence_transformers, "CrossEncoder",
            lambda *_a, **_k: (_ for _ in ()).throw(OSError("boom")),
        )
        reranker = CrossEncoderReranker(model_name="fake/reranker")
        with pytest.raises(RerankerUnavailable):
            reranker.warmup()


class TestSingleton:
    @pytest.fixture(autouse=True)
    def _isolate_singleton(self):
        """单例是进程级状态：不隔离会让用例之间通过全局缓存互相影响"""
        reset_reranker_cache()
        yield
        reset_reranker_cache()

    def test_get_reranker_returns_same_instance(self):
        assert get_reranker() is get_reranker()

    def test_reset_clears_cache(self):
        first = get_reranker()
        reset_reranker_cache()
        assert get_reranker() is not first

    def test_lazy_load_does_not_touch_model(self):
        """构造精排器不应加载权重：未启用精排的部署不该承担这份内存"""
        reranker = get_reranker()
        assert reranker.is_loaded is False
        assert reranker.load_error is None


class TestConstructorValidation:
    @pytest.mark.parametrize("model_name", ["", "   "])
    def test_blank_model_name_rejected(self, model_name):
        with pytest.raises(ValueError, match="model_name"):
            CrossEncoderReranker(model_name=model_name)

    def test_invalid_batch_size_rejected(self):
        with pytest.raises(ValueError, match="batch_size"):
            CrossEncoderReranker(model_name="fake/reranker", batch_size=0)

    def test_nan_warning_emitted(self, caplog):
        reranker = _reranker(lambda _q, _p: float("nan"))
        with caplog.at_level(logging.WARNING, logger="app.utils.reranker"):
            reranker.rerank("q", [("a", "x")])
        assert any("NaN" in record.message for record in caplog.records)


class TestScoreBatch:
    def test_score_returns_float_list_aligned_with_input(self):
        reranker = _reranker(lambda _q, passage: len(passage) * 0.5)
        scores = reranker.score("q", ["a", "bb", "ccc"])

        assert scores == [0.5, 1.0, 1.5]
        assert all(isinstance(value, float) for value in scores)

    def test_no_nan_leaks_into_result(self):
        reranker = _reranker(lambda _q, _p: float("nan"))
        assert all(not math.isnan(value) for value in reranker.score("q", ["a"]))
