"""``app.utils.retrieval_context`` 的纯函数契约（P4 上下文装配）

本文件覆盖「装配文本长什么样」这类**不需要数据库、不需要模型**的判定，因此可以
把边界情形穷举到位。装配层最容易出的两类错都在这里被钉住：

1. **出处标记把粗化当成精确定位**——``heading_path_mixed`` 为真时仍输出
   ``§ A``，于是引用断言「本块出自 A」，而 A 恰是块里唯一没有的那一节；
2. **邻块拼接把重叠算错**——分块带 64 字符重叠，直接拼接会让同一句在上下文里
   出现两次，既浪费预算又让模型把一句话当成两条独立证据。

``collect_window_indexes`` 单独成函数就是为了让「窗口到底含哪些下标」可被直接
断言：窗口半径的边界（首块无前邻、末块无后邻、radius=0）过去散落在服务层内联
计算里，没有测试能覆盖。
"""

from __future__ import annotations

import pytest

from app.utils.retrieval_context import (
    CHUNK_TYPE_LABELS,
    PAGE_RANGE_SEP,
    build_context_header,
    collect_window_indexes,
    format_chunk_type,
    format_heading_scope,
    format_page_range,
    iter_unique,
    join_window,
    trim_overlap,
)


class TestPageRange:
    def test_single_page(self):
        """单页块两端相等，应退化成单值而非「p.37–37」"""
        assert format_page_range(37, 37) == "p.37"

    def test_cross_page_uses_en_dash(self):
        """跨页块给闭区间；连接符必须是 en dash（与前端 citation.ts 同一字符）"""
        assert format_page_range(37, 38) == f"p.37{PAGE_RANGE_SEP}38"
        assert "-" not in format_page_range(37, 38)

    def test_missing_end_falls_back_to_start(self):
        """``page_end`` 缺失（旧数据迁移前的行）时按单页呈现，不产出 p.37–None"""
        assert format_page_range(37, None) == "p.37"

    def test_no_page_at_all(self):
        """非 PDF 无页码：必须返回 None，而不是空串——两者在调用方是同一件事"""
        assert format_page_range(None, None) is None


class TestHeadingScope:
    def test_exact_path(self):
        assert format_heading_scope("3.2 学习路径") == "§ 3.2 学习路径"

    def test_mixed_must_say_etc(self):
        """粗化标记必须落到文案上，否则该标记等于没实现"""
        assert format_heading_scope("3.2 学习路径", mixed=True) == "§ 3.2 学习路径 等小节"

    def test_absent_path(self):
        assert format_heading_scope(None) is None
        assert format_heading_scope("") is None


class TestContextHeader:
    def test_pdf_header_has_pages_without_heading(self):
        """PDF 只有页码没有标题路径：不能要求「三者齐全才输出」"""
        assert build_context_header(doc_name="手册.pdf", page=37, page_end=38) == (
            f"[《手册.pdf》 | p.37{PAGE_RANGE_SEP}38]"
        )

    def test_markdown_header_has_heading_without_pages(self):
        """md/docx 只有标题路径没有页码：同上，按需出现"""
        assert build_context_header(doc_name="notes.md", heading_path="A > B") == (
            "[《notes.md》 | § A > B]"
        )

    def test_full_header_orders_doc_scope_page(self):
        """三个成分固定顺序：先「哪份文件」、再「哪一节」、最后「哪几页」"""
        header = build_context_header(
            doc_name="手册.pdf",
            heading_path="A",
            page=1,
            page_end=2,
        )
        assert header == f"[《手册.pdf》 | § A | p.1{PAGE_RANGE_SEP}2]"

    def test_nothing_to_cite_returns_none(self):
        """无任何可标注出处时返回 None，调用方只需判断真值"""
        assert build_context_header() is None

    def test_doc_name_only_is_valid(self):
        """仅有文件名也是一条有效出处（比什么都不给强）"""
        assert build_context_header(doc_name="a.pdf") == "[《a.pdf》]"


class TestChunkTypeLabel:
    """块类型标签（P1 类型贯通）

    标记的作用是**换一种读法**：表格是二维的、代码是逐字敏感的、图片块本身没有
    可读正文。而 ``text`` / ``title`` 刻意不加标签——给正文标一个 ``[正文]`` 是
    零信息量的噪音，只会挤占本已紧张的上下文预算。
    """

    def test_structural_types_get_labels(self):
        assert format_chunk_type("table") == "表格"
        assert format_chunk_type("code") == "代码"
        assert format_chunk_type("image") == "图片"

    def test_plain_text_types_get_no_label(self):
        """``text`` / ``title`` 不加标签：返回 None 而非空串，调用方只判真值"""
        assert format_chunk_type("text") is None
        assert format_chunk_type("title") is None

    def test_missing_or_unknown_type_is_silent(self):
        """存量引用对象没有 ``chunk_type`` 键；未知类型一律静默不带标签"""
        assert format_chunk_type(None) is None
        assert format_chunk_type("") is None
        assert format_chunk_type("whatever") is None

    def test_header_places_type_after_doc_before_scope(self):
        """成分顺序固定为 文件 → 类型 → 小节 → 页码

        顺序固定使标记可被机械解析，也让同一份文档的标记在多次检索中逐字一致。
        """
        header = build_context_header(
            doc_name="手册.pdf",
            chunk_type="table",
            heading_path="A",
            page=1,
            page_end=2,
        )
        assert header == f"[《手册.pdf》 | 表格 | § A | p.1{PAGE_RANGE_SEP}2]"

    def test_type_alone_is_a_valid_header(self):
        """只有类型也是一条有效标记：不能因为「三者不全」就整条丢弃"""
        assert build_context_header(chunk_type="code") == "[代码]"

    def test_plain_type_does_not_change_header(self):
        """``text`` 走的是与「没有类型」完全相同的路径

        这条钉住的是**向后兼容**：所有既有断言（不含 ``chunk_type`` 参数）必须
        继续逐字符成立，否则每一条历史上下文的字节数都会变化，而那是评测基线。
        """
        assert build_context_header(doc_name="a.pdf", chunk_type="text") == (
            build_context_header(doc_name="a.pdf")
        )
        assert build_context_header(doc_name="a.pdf", chunk_type=None) == (
            build_context_header(doc_name="a.pdf")
        )

    def test_every_labelled_type_is_distinguishable(self):
        """标签表只允许放「值得提示模型」的类型

        反向守卫：类型一旦被加进标签表，就是在告诉模型「这段内容换一种读法」。
        把 ``text`` 之类的普通类型加进去不会让任何测试失败，只会让每次检索都多
        一个零信息前缀——所以这里显式禁止。
        """
        assert set(CHUNK_TYPE_LABELS) == {"table", "code", "image"}
        assert "text" not in CHUNK_TYPE_LABELS
        assert "title" not in CHUNK_TYPE_LABELS


class TestTrimOverlap:
    def test_trims_exact_overlap(self):
        """相邻块的重叠部分必须裁掉，只保留新内容"""
        assert trim_overlap("ABCDEFGH", "EFGHIJ", 4) == "IJ"

    def test_keeps_text_when_no_overlap(self):
        assert trim_overlap("ABCDEFGH", "XYZ", 4) == "XYZ"

    def test_respects_max_overlap_bound(self):
        """重叠窗口有界：超过 max_overlap 的公共部分**不**当作重叠

        这条是有意的取舍——真实分块器的重叠不会超过 chunk_overlap，把「更长的
        公共子串」也当重叠去裁，会在正文本身重复出现时误删内容。
        """
        assert trim_overlap("XYZABCDEFGH", "ABCDEFGH", 4) == "ABCDEFGH"

    def test_zero_overlap_is_noop(self):
        assert trim_overlap("ABCD", "AB", 0) == "AB"

    def test_empty_side_is_noop(self):
        assert trim_overlap("", "AB", 4) == "AB"
        assert trim_overlap("AB", "", 4) == ""

    def test_fully_covered_chunk_becomes_empty(self):
        """整块被前一块末尾覆盖时裁成空串，由 join_window 负责跳过"""
        assert trim_overlap("ABCDEFGH", "EFGH", 4) == ""


class TestJoinWindow:
    def test_joins_with_blank_line(self):
        """块间用空行分隔：结构边界落在段落边界上，单换行会让两块读起来像一段"""
        assert join_window(["第一段", "第二段"], overlap=0) == "第一段\n\n第二段"

    def test_trims_overlap_between_neighbors(self):
        assert join_window(["ABCDEFGH", "EFGHIJ"], overlap=4) == "ABCDEFGH\n\nIJ"

    def test_three_chunk_chain_uses_raw_previous(self):
        """三块连续重叠时逐级裁对（每块只保留自己的新增部分）

        以**上一块原文**而非裁剩文本为参照：裁剩文本可能短于真实重叠长度，会让
        检测窗口收缩而漏裁。这里三块首尾各重叠 4 字符，逐级裁剪后恰好是
        ``ABCDEFGH`` / ``IJKL`` / ``MNOP``。
        """
        window = join_window(["ABCDEFGH", "EFGHIJKL", "IJKLMNOP"], overlap=4)
        assert window == "ABCDEFGH\n\nIJKL\n\nMNOP"

    def test_skips_chunk_fully_covered_by_previous(self):
        """裁成空串的块直接跳过，不留连续空行（会让模型以为中间省略了内容）"""
        assert join_window(["ABCDEFGH", "EFGH", "ZZZ"], overlap=4) == "ABCDEFGH\n\nZZZ"

    def test_empty_input(self):
        assert join_window([], overlap=4) == ""


class TestWindowIndexes:
    def test_radius_one_includes_neighbors(self):
        assert collect_window_indexes(5, 1) == [4, 5, 6]

    def test_first_chunk_has_no_negative_index(self):
        """首块没有前邻：下标不得为负（负数下标在 SQL 里查不到，却会静默少一块）"""
        assert collect_window_indexes(0, 1) == [0, 1]

    def test_radius_zero_is_self_only(self):
        assert collect_window_indexes(5, 0) == [5]

    def test_larger_radius(self):
        assert collect_window_indexes(5, 2) == [3, 4, 5, 6, 7]


class TestIterUnique:
    def test_preserves_first_seen_order(self):
        """去重保持首次出现顺序：让日志与断言稳定，不依赖 set 的迭代顺序"""
        assert iter_unique([3, 1, 3, 2, 1]) == [3, 1, 2]

    def test_empty(self):
        assert iter_unique([]) == []
