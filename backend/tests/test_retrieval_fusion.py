"""混合检索分数融合的契约

融合是混合检索里**唯一决定质量**的环节：召回两路都是现成的，怎么合才是问题所在。
因此本文件重点守护四件事：

1. **归一化确实发生**。两个分支的分数尺度相差一个数量级（余弦 ∈ [0,1]，BM25 无界），
   不归一化就等于 α 失效——不管 α 设多少，结果都只由 BM25 的绝对值决定。
   这里用一个「若不做归一化则结论必然相反」的用例把该性质钉住。
2. **α 的语义边界**。α=1.0 必须逐位退化为纯稠密（这是「开关关闭时行为等价」的
   可验证依据），α=0.0 退化为纯词法。
3. **并列的确定性**。并列时的落位顺序必须由代码规定，而不是偶然依赖字典遍历顺序，
   否则同一份输入在不同进程里可能给出不同排序，评测与线上随之分叉。
4. **非法输入必须显式失败**。静默截断长度不一致的输入会让融合结果整体偏移而无人察觉。
"""

from __future__ import annotations

import pytest

from app.utils.retrieval_fusion import minmax_normalize, weighted_fuse


class TestMinMaxNormalize:
    def test_maps_to_unit_interval(self):
        assert minmax_normalize([2.0, 4.0, 6.0]) == [0.0, 0.5, 1.0]

    def test_empty_returns_empty(self):
        assert minmax_normalize([]) == []

    def test_all_equal_returns_ones(self):
        """全部相等时相对顺序无信息。返回 1.0 而非 0.0：让该分支与另一分支的
        最高分候选并列，交由并列规则裁量，而不是让整条分支退出融合。"""
        assert minmax_normalize([7.0, 7.0, 7.0]) == [1.0, 1.0, 1.0]

    def test_single_value_returns_one(self):
        assert minmax_normalize([0.42]) == [1.0]

    def test_preserves_relative_order(self):
        normalized = minmax_normalize([0.9, 0.1, 0.5])
        assert normalized[0] > normalized[2] > normalized[1]


class TestWeightedFuse:
    def test_alpha_one_degenerates_to_dense(self):
        """α=1.0 必须逐位等于稠密结果——这是「混合检索关闭时行为等价」的锚点"""
        fused = weighted_fuse(["a", "b"], [0.9, 0.8], ["c", "a"], [30.0, 20.0], alpha=1.0)
        assert fused == [("a", 0.9), ("b", 0.8)]

    def test_alpha_zero_degenerates_to_sparse(self):
        fused = weighted_fuse(["a", "b"], [0.9, 0.8], ["c", "a"], [30.0, 20.0], alpha=0.0)
        assert fused == [("c", 30.0), ("a", 20.0)]

    def test_normalization_is_what_makes_alpha_matter(self):
        """反例守卫：**不做归一化**时，α=0.5 也无法阻止 BM25 的绝对尺度压倒余弦

        稠密分数是 0.9/0.1，词法分数是 30/1（量级差约 30 倍）。归一化后两路都在
        [0,1]，α=0.5 时稠密第一位（a）应胜过词法第一位（c）；若直接相加，
        c 会以绝对分 30 压过 a 的 0.9，结论翻转。本用例把「归一化真的生效」钉死。
        """
        fused = weighted_fuse(
            ["a", "b"], [0.9, 0.1], ["c", "d"], [30.0, 1.0], alpha=0.5
        )
        order = [doc_id for doc_id, _ in fused]
        assert order[0] == "a", "归一化未生效：BM25 的绝对分数压过了稠密分数"

    def test_item_present_in_both_branches_accumulates(self):
        """两路都命中的条目应获得两侧加权之和，从而排到只命中一路的条目之前"""
        fused = dict(
            weighted_fuse(["a", "b"], [0.9, 0.1], ["a", "c"], [30.0, 1.0], alpha=0.7)
        )
        assert fused["a"] == pytest.approx(0.7 * 1.0 + 0.3 * 1.0)
        assert fused["a"] > fused["b"]
        assert fused["a"] > fused["c"]

    def test_only_dense_items_keep_dense_relative_order(self):
        fused = weighted_fuse(["a", "b", "c"], [0.9, 0.5, 0.1], [], [], alpha=0.7)
        assert [doc_id for doc_id, _ in fused] == ["a", "b", "c"]

    def test_empty_both_sides_returns_empty(self):
        assert weighted_fuse([], [], [], [], alpha=0.7) == []

    def test_sparse_only_items_are_kept_not_dropped(self):
        """词法独有项必须保留：混合检索的收益恰恰来自稠密漏召回时词法捞回来的部分"""
        fused = weighted_fuse(["a"], [0.9], ["b"], [10.0], alpha=0.7)
        assert {doc_id for doc_id, _ in fused} == {"a", "b"}

    def test_ties_resolve_dense_first(self):
        """并列时稠密分支优先，且该规则是确定性的

        构造：a 只在稠密出现（归一化 1.0 → 0.7），b 只在词法出现（归一化 1.0 → 0.3）。
        再令两侧各有一个归一化为 0 的项，使并列确实发生在同分条目之间。
        """
        fused = weighted_fuse(["a", "b"], [1.0, 0.0], ["c", "d"], [1.0, 0.0], alpha=0.5)
        scores = dict(fused)
        # a 与 c 同分（都是 0.5），稠密的 a 应在前
        assert scores["a"] == pytest.approx(scores["c"])
        order = [doc_id for doc_id, _ in fused]
        assert order.index("a") < order.index("c")

    def test_missing_side_counts_as_zero_contribution(self):
        """只在词法出现的条目，其融合分只含词法项，不应被当作「稠密给了 0 分」而特殊对待"""
        only_sparse = dict(weighted_fuse(["a"], [0.9], ["z"], [5.0], alpha=0.6))
        assert only_sparse["z"] == pytest.approx(0.6 * 1.0 * 0 + 0.4 * 1.0)

    def test_result_is_sorted_descending(self):
        fused = weighted_fuse(["a", "b", "c"], [0.9, 0.5, 0.1], ["c", "b"], [9.0, 5.0], alpha=0.5)
        scores = [score for _, score in fused]
        assert scores == sorted(scores, reverse=True)


class TestValidation:
    def test_alpha_below_range_rejected(self):
        with pytest.raises(ValueError):
            weighted_fuse(["a"], [1.0], ["b"], [1.0], alpha=-0.1)

    def test_alpha_above_range_rejected(self):
        with pytest.raises(ValueError):
            weighted_fuse(["a"], [1.0], ["b"], [1.0], alpha=1.1)

    def test_dense_length_mismatch_rejected(self):
        """静默截断会让融合结果整体偏移且不报错，必须显式失败"""
        with pytest.raises(ValueError):
            weighted_fuse(["a", "b"], [1.0], ["c"], [1.0], alpha=0.5)

    def test_sparse_length_mismatch_rejected(self):
        with pytest.raises(ValueError):
            weighted_fuse(["a"], [1.0], ["c", "d"], [1.0], alpha=0.5)
