"""指标模块单测：全部期望值均由公式手算得出，不接受「跑一遍看结果」式的断言

每个用例都在注释中给出推导过程，目的是让评审人能独立复核，
而不是只能相信测试通过。
"""

import math

import pytest

from app.rag_eval.metrics import (
    average_precision_at_k,
    dcg_at_k,
    hit_at_k,
    macro_average,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank_at_k,
    summarize_by_key,
)

# 基准用例：相关集 {b, d}，检索结果 a,b,c,d,e
RETRIEVED = ["a", "b", "c", "d", "e"]
RELEVANT = ["b", "d"]


class TestRecallAtK:
    def test_partial_recall_uses_complete_relevant_set_as_denominator(self):
        """/@3：top3={a,b,c} 命中 {b} → 1/|R|=1/2=0.5

        分母必须是完整相关集（2），而不是 top3 中实际出现的相关项数（1）。
        否则会得到 1.0，Recall 被系统性高估。
        """
        assert recall_at_k(RETRIEVED, RELEVANT, 3) == pytest.approx(0.5)

    def test_full_recall_when_all_relevant_retrieved(self):
        """@5：top5 覆盖 {b,d} → 2/2 = 1.0"""
        assert recall_at_k(RETRIEVED, RELEVANT, 5) == pytest.approx(1.0)

    def test_monotonic_in_k(self):
        """Recall@k 随 k 单调不减"""
        values = [recall_at_k(RETRIEVED, RELEVANT, k) for k in range(1, 6)]
        assert values == sorted(values)

    def test_k_beyond_retrieved_length_is_not_error(self):
        """k 超出结果长度：按实际可得结果计算，分母仍为完整相关集"""
        assert recall_at_k(["b"], ["b"], 10) == pytest.approx(1.0)


class TestHitAndPrecision:
    def test_hit_at_1_is_zero_when_first_result_is_irrelevant(self):
        """rank1 是 'a'，不在相关集内 → 0.0"""
        assert hit_at_k(RETRIEVED, RELEVANT, 1) == 0.0

    def test_hit_at_3_is_one(self):
        """top3 含 'b' → 1.0"""
        assert hit_at_k(RETRIEVED, RELEVANT, 3) == 1.0

    def test_precision_denominator_is_k_not_result_count(self):
        """P@3 = 1/3；分母固定为 k，便于跨查询横向比较"""
        assert precision_at_k(RETRIEVED, RELEVANT, 3) == pytest.approx(1 / 3)

    def test_precision_with_k_beyond_results_still_divides_by_k(self):
        """只返回 1 条但 k=10：P@10 = 1/10，体现「位置空着也是成本」"""
        assert precision_at_k(["b"], ["b"], 10) == pytest.approx(0.1)


class TestRankingMetrics:
    def test_reciprocal_rank_uses_first_hit_position(self):
        """首命中在 rank2 → 1/2"""
        assert reciprocal_rank_at_k(RETRIEVED, RELEVANT, 3) == pytest.approx(0.5)

    def test_reciprocal_rank_zero_when_no_hit_within_k(self):
        """k=1 时 top1 不相关 → 0（未命中记 0，而非记 1）"""
        assert reciprocal_rank_at_k(RETRIEVED, RELEVANT, 1) == 0.0

    def test_average_precision_hand_computed(self):
        """AP@3：命中在 rank2 → Σ P@i·rel(i) = 1/2；再除以 |R|=2 → 0.25"""
        assert average_precision_at_k(RETRIEVED, RELEVANT, 3) == pytest.approx(0.25)

    def test_average_precision_penalises_missed_relevant(self):
        """未召回的相关项以 0 计入分母，构成惩罚

        retrieved=[b]（只召回 1 条），relevant={b,d}：
        AP@1 = (P@1) / |R| = (1/1) / 2 = 0.5
        若分母误用「已召回的相关项数」，这里会得到 1.0 —— 召回不全反而满分。
        """
        assert average_precision_at_k(["b"], ["b", "d"], 1) == pytest.approx(0.5)

    def test_average_precision_no_hit_at_rank_1_is_zero(self):
        """top1 不相关 → AP@1 = 0.0（首位相关性直接决定该 k 下的 AP）"""
        assert average_precision_at_k(RETRIEVED, RELEVANT, 1) == 0.0


class TestNdcg:
    def test_ndcg_binary_hand_computed(self):
        """二值增益 {b:1, d:1}，k=3

        DCG@3  = 1/log2(3)                      ≈ 0.63093   （命中在 rank2）
        IDCG@3 = 1/log2(2) + 1/log2(3)          ≈ 1.63093   （理想排序 b,d 占满前两位）
        nDCG   = 0.63093 / 1.63093              ≈ 0.38685
        """
        expected = (1 / math.log2(3)) / (1 / math.log2(2) + 1 / math.log2(3))
        assert ndcg_at_k(RETRIEVED, {"b": 1, "d": 1}, 3) == pytest.approx(expected)

    def test_ndcg_graded_gains_hand_computed(self):
        """分级增益 {a:2, b:1}，检索顺序 b,a（把高相关的排到了后面）

        DCG  = (2^1-1)/log2(2) + (2^2-1)/log2(3) = 1 + 3/1.58496 ≈ 2.89279
        IDCG = (2^2-1)/log2(2) + (2^1-1)/log2(3) = 3 + 0.63093   ≈ 3.63093
        nDCG ≈ 0.79669   —— 明显低于 1.0，体现「顺序错了要扣分」
        """
        expected = (1 / math.log2(2) + 3 / math.log2(3)) / (3 / math.log2(2) + 1 / math.log2(3))
        assert ndcg_at_k(["b", "a"], {"a": 2, "b": 1}, 2) == pytest.approx(expected)
        assert ndcg_at_k(["b", "a"], {"a": 2, "b": 1}, 2) < 0.8

    def test_ndcg_perfect_ranking_is_one(self):
        """理想排序下 nDCG == 1.0"""
        assert ndcg_at_k(["a", "b"], {"a": 2, "b": 1}, 2) == pytest.approx(1.0)

    def test_dcg_ignores_unknown_ids(self):
        """未出现在 gains 中的 id 视为增益 0"""
        assert dcg_at_k(["zzz"], {"a": 1}, 1) == 0.0

    def test_ndcg_ideal_shorter_than_k_is_not_penalised(self):
        """|R| < k 时不应因为「填不满 k 个位置」被扣分：单相关项 @10 仍为 1.0"""
        assert ndcg_at_k(["b"], {"b": 1}, 10) == pytest.approx(1.0)

    def test_ndcg_without_positive_gain_raises(self):
        """无正增益 = 无标准答案，指标无定义，必须显式报错"""
        with pytest.raises(ValueError, match="positive gain"):
            ndcg_at_k(["b"], {"b": 0}, 3)


class TestEdgeCases:
    def test_empty_relevant_raises_instead_of_returning_zero(self):
        """无相关集时不能返回 0 —— 那会把「标注缺失」伪装成「检索失败」"""
        with pytest.raises(ValueError, match="non-empty"):
            recall_at_k(["a"], [], 5)

    @pytest.mark.parametrize("bad_k", [0, -1])
    def test_non_positive_k_raises(self, bad_k):
        with pytest.raises(ValueError, match="k must be >= 1"):
            recall_at_k(RETRIEVED, RELEVANT, bad_k)

    def test_non_integer_k_raises(self):
        with pytest.raises(TypeError, match="k must be an int"):
            recall_at_k(RETRIEVED, RELEVANT, 3.5)  # type: ignore[arg-type]

    def test_duplicate_ids_are_deduped_keeping_first_position(self):
        """重复 id 去重后保留首次出现位置，避免同一文档占多个名次

        retrieved=[b,b,x] 去重为 [b,x]：R@2 仍为 1.0（不因重复而虚高），
        P@2 = 1/2（去重后只有 2 个位置，不是 3 个）。
        """
        assert recall_at_k(["b", "b", "x"], ["b"], 2) == pytest.approx(1.0)
        assert precision_at_k(["b", "b", "x"], ["b"], 2) == pytest.approx(0.5)
        assert reciprocal_rank_at_k(["b", "b", "x"], ["b"], 3) == pytest.approx(1.0)

    def test_ties_do_not_break_scoring(self):
        """并列名次（同分）不影响指标：指标只看 id 与位置"""
        assert reciprocal_rank_at_k(["x", "y", "b"], ["b"], 3) == pytest.approx(1 / 3)


class TestAggregation:
    def test_macro_average_skips_undefined_values(self):
        """跳过 None，仅对可评分查询求平均"""
        assert macro_average([1.0, None, 0.0, None]) == pytest.approx(0.5)

    def test_macro_average_all_undefined_returns_none(self):
        """全部无定义时返回 None，而不是伪造 0.0"""
        assert macro_average([None, None]) is None

    def test_summarize_by_key_groups_queries(self):
        """按查询类型分组求宏观平均"""
        result = summarize_by_key(
            {"q1": 1.0, "q2": 0.0, "q3": 0.5},
            {"q1": "fact", "q2": "fact", "q3": "exact_term"},
        )
        assert result == {"exact_term": 0.5, "fact": 0.5}

    def test_summarize_by_key_unknown_group_fallback(self):
        """未标注类型的查询归入 unknown，不静默丢弃"""
        result = summarize_by_key({"q1": 1.0}, {})
        assert result == {"unknown": 1.0}
