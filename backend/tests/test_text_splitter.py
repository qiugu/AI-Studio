"""文本分块器单测

分块质量是检索质量的上游：分块切断了答案，检索再强也召不回。
本文件既验证可依赖的不变量，也把已知缺陷固化为**严格 xfail**——
缺陷修复后该用例会变为 XPASS 并使测试失败，从而强制移除标记，
避免「缺陷已修但标注还在」的长期错配。
"""

import pytest

from app.utils.document import TextSplitter


def _long_text(sentences: int = 300) -> str:
    return "".join(f"第{i}句内容用于验证分块边界与重叠行为。" for i in range(sentences))


def _suffix_prefix_overlap(previous: str, following: str, max_check: int = 200) -> int:
    """返回相邻两块的公共重叠长度（前者后缀 == 后者前缀）"""
    limit = min(max_check, len(previous), len(following))
    for size in range(limit, 0, -1):
        if previous[-size:] == following[:size]:
            return size
    return 0


class TestSplitterInvariants:
    def test_chunks_are_substrings_of_source(self):
        """任何分块都必须是原文的连续子串——分块过程不得改写或臆造内容"""
        text = _long_text()
        for chunk in TextSplitter(chunk_size=200, chunk_overlap=50).split(text):
            assert chunk in text

    def test_chunk_order_preserved(self):
        """分块顺序必须与原文顺序一致，否则引用定位会错乱"""
        text = _long_text()
        chunks = TextSplitter(chunk_size=200, chunk_overlap=30).split(text)
        cursor = 0
        for chunk in chunks:
            position = text.find(chunk, cursor)
            assert position >= cursor, "分块顺序发生回退"
            cursor = position

    def test_no_empty_chunks(self):
        """不得产出空串或纯空白块——它们会污染向量并产生无意义的检索结果"""
        chunks = TextSplitter(chunk_size=200, chunk_overlap=30).split(_long_text())
        assert chunks
        assert all(chunk.strip() for chunk in chunks)

    def test_short_text_yields_single_chunk(self):
        text = "这是一段很短的文本。"
        assert TextSplitter(chunk_size=1024).split(text) == [text]

    def test_respects_chunk_size_for_sentence_text(self):
        """以句号分隔的规整文本，每块长度不应超过 chunk_size"""
        chunks = TextSplitter(chunk_size=100, chunk_overlap=0).split(_long_text())
        assert chunks
        assert all(len(chunk) <= 100 for chunk in chunks)

    def test_covers_entire_text_without_overlap(self):
        """重叠为 0 时，所有分块的长度之和应接近原文（允许分隔符在块边界被丢弃）"""
        text = _long_text(sentences=100)
        chunks = TextSplitter(chunk_size=100, chunk_overlap=0).split(text)
        total = sum(len(chunk) for chunk in chunks)
        assert total >= len(text) * 0.9, f"内容丢失过多：原文 {len(text)}，分块合计 {total}"

    def test_invalid_empty_input_returns_empty(self):
        assert TextSplitter().split("") == []
        assert TextSplitter().split("   \n  ") == []


class TestKnownDefects:
    @pytest.mark.xfail(
        strict=True,
        reason=(
            "D11：`TextSplitter._merge_splits` 只比较 `len(current) + len(s) + separator_len`，"
            "从未把 `chunk_overlap` 纳入计算，因此声明的 128 字符重叠实际为 0。"
            "后果：跨块边界的答案会被一分为二，任何一块都无法独立支撑答案，"
            "直接压低 Recall 上限。计划在 Phase 5 修复。"
        ),
    )
    def test_consecutive_chunks_should_overlap(self):
        """相邻分块应存在重叠（当前实现重叠为 0）"""
        chunks = TextSplitter(chunk_size=200, chunk_overlap=50).split(_long_text())
        assert len(chunks) >= 2, "文本不足以产生多个分块，用例前提不成立"
        assert _suffix_prefix_overlap(chunks[0], chunks[1]) > 0

    def test_overlap_helpers_agree_on_zero_overlap(self):
        """辅助函数自检：确保上面的 xfail 不是由断言写法错误造成的假阴性"""
        text = _long_text()
        chunks = TextSplitter(chunk_size=200, chunk_overlap=50).split(text)
        assert len(chunks) >= 2
        assert _suffix_prefix_overlap(chunks[0], chunks[1]) == 0
