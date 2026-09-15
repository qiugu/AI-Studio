"""分段解析与段内分块单测（方案 §2）

本文件守住两条契约，它们分别是「元数据可信」与「入库文本不变」的前提：

1. **元数据契约**——每段的 ``page`` / ``heading_path`` 要么精确，要么为 ``None``。
   不得用字号、加粗、位置等启发式把猜测写进「出处」字段：本项目的结果里
   ``source_page`` / ``heading_path`` 是给人核对出处用的，写错比留空更糟。
2. **无损契约**——``DocumentParser.parse(f, t)`` 必须逐字符等于
   ``"\\n".join(s.text for s in DocumentParser.parse_segments(f, t))``。
   分段只是把同一份文本切开，不得增删任何字符；一旦破坏，加元数据的改动会
   **静默改变入库文本**，而检索质量下降不会指回这里。

分块侧另守一条：分块在**段内**进行，块边界不得跨越段边界——否则块的页码/
标题归属就不再是一对一的，元数据退化成一个近似值。
"""

import sys
import types

import pytest

from app.utils.document import (
    DocumentParser,
    TextSegment,
    TextSplitter,
    TextChunk,
)


def _join(segments) -> str:
    return "\n".join(s.text for s in segments)


# ────────────────────────────── .txt ──────────────────────────────

class TestParseTextSegments:
    def test_single_segment_without_metadata(self, tmp_path):
        """纯文本无结构信息：整份文件作为一段，元数据全为 None"""
        path = tmp_path / "a.txt"
        path.write_text("第一行\n第二行\n", encoding="utf-8")

        segments = DocumentParser.parse_segments(str(path), "txt")

        assert len(segments) == 1
        assert segments[0].text == "第一行\n第二行\n"
        assert segments[0].page is None
        assert segments[0].heading_path is None

    def test_lossless_against_parse(self, tmp_path):
        path = tmp_path / "a.txt"
        path.write_text("alpha\nbeta\n\ngamma", encoding="utf-8")

        assert DocumentParser.parse(str(path), "txt") == _join(
            DocumentParser.parse_segments(str(path), "txt")
        )


# ────────────────────────────── .md ──────────────────────────────

class TestParseMarkdownSegments:
    def test_heading_path_is_exact_per_level(self, tmp_path):
        """标题路径按层级栈归并：同级标题互不串味，回退时弹出更深层级"""
        path = tmp_path / "doc.md"
        path.write_text(
            "# A\nintro\n"
            "## B\ntext-b\n"
            "### C\ndeep\n"
            "## D\ntext-d\n",
            encoding="utf-8",
        )

        segments = DocumentParser.parse_segments(str(path), "md")

        assert [s.heading_path for s in segments] == [
            "A",
            "A > B",
            "A > B > C",
            "A > D",
        ]

    def test_heading_belongs_to_its_own_section(self, tmp_path):
        """标题行归属紧随其后的内容段：块自描述，且标题本身可被检索命中"""
        path = tmp_path / "doc.md"
        path.write_text("# 标题\n正文", encoding="utf-8")

        segments = DocumentParser.parse_segments(str(path), "md")

        assert len(segments) == 1
        assert segments[0].text == "# 标题\n正文"
        assert segments[0].heading_path == "标题"

    def test_blank_lines_preserved(self, tmp_path):
        """空行必须保留：丢掉空行会让 parse() 与原文不再逐字符相等"""
        path = tmp_path / "doc.md"
        content = "# A\n\n正文\n\n\n尾部"
        path.write_text(content, encoding="utf-8")

        assert DocumentParser.parse(str(path), "md") == _join(
            DocumentParser.parse_segments(str(path), "md")
        )

    def test_trailing_hashes_trimmed_from_title(self, tmp_path):
        """闭合式标题 ``## 标题 ##`` 的路径不应带尾随 ``#``"""
        path = tmp_path / "doc.md"
        path.write_text("## 标题 ##\n内容\n", encoding="utf-8")

        segments = DocumentParser.parse_segments(str(path), "md")

        assert segments[0].heading_path == "标题"

    def test_hash_without_space_is_not_a_heading(self, tmp_path):
        """``#tag`` 不是 ATX 标题（缺少空格），不得污染标题路径"""
        path = tmp_path / "doc.md"
        path.write_text("#not-a-heading\n内容\n", encoding="utf-8")

        segments = DocumentParser.parse_segments(str(path), "md")

        assert len(segments) == 1
        assert segments[0].heading_path is None

    def test_no_heading_file_has_none_path(self, tmp_path):
        path = tmp_path / "doc.md"
        path.write_text("纯正文\n没有标题\n", encoding="utf-8")

        segments = DocumentParser.parse_segments(str(path), "md")

        assert all(s.heading_path is None for s in segments)

    def test_page_is_always_none(self, tmp_path):
        """Markdown 无分页概念：不得编造页码"""
        path = tmp_path / "doc.md"
        path.write_text("# A\ntext\n## B\ntext2\n", encoding="utf-8")

        assert all(
            s.page is None for s in DocumentParser.parse_segments(str(path), "md")
        )

    def test_lossless_against_parse(self, tmp_path):
        path = tmp_path / "doc.md"
        path.write_text(
            "# A\n\n正文一\n## B\n正文二\n### C\n正文三\n# A2\n尾\n",
            encoding="utf-8",
        )

        assert DocumentParser.parse(str(path), "md") == _join(
            DocumentParser.parse_segments(str(path), "md")
        )


# ────────────────────────────── .pdf ──────────────────────────────

class _StubPage:
    def __init__(self, text):
        self._text = text

    def extract_text(self):
        return self._text


def _install_stub_pdf(monkeypatch, pages_text):
    """把假的 ``pypdf`` 注入 ``sys.modules``，使解析无需真实 PDF 文件"""
    module = types.ModuleType("pypdf")

    class _StubReader:
        def __init__(self, _path):
            self.pages = [_StubPage(t) for t in pages_text]

    module.PdfReader = _StubReader
    monkeypatch.setitem(sys.modules, "pypdf", module)
    return module


class TestParsePdfSegments:
    def test_one_segment_per_page_with_one_based_page(self, monkeypatch):
        """一页一段，页码为 1 基（与阅读器显示一致）"""
        _install_stub_pdf(monkeypatch, ["第1页正文", "第2页正文"])

        segments = DocumentParser.parse_segments("whatever.pdf", "pdf")

        assert [s.text for s in segments] == ["第1页正文", "第2页正文"]
        assert [s.page for s in segments] == [1, 2]

    def test_heading_path_is_always_none(self, monkeypatch):
        """pypdf 只给文本流：不得据版式猜测标题"""
        _install_stub_pdf(monkeypatch, ["a", "b"])

        assert all(
            s.heading_path is None
            for s in DocumentParser.parse_segments("whatever.pdf", "pdf")
        )

    def test_blank_page_normalized_to_empty_string(self, monkeypatch):
        """``extract_text()`` 对空白页返回 ``None``：须归一为 ``""``

        旧实现把它直接塞进 ``"\\n".join``，这类页面会以 ``TypeError`` 崩掉整次解析。
        """
        _install_stub_pdf(monkeypatch, ["第1页", None, "第3页"])

        segments = DocumentParser.parse_segments("whatever.pdf", "pdf")

        assert [s.text for s in segments] == ["第1页", "", "第3页"]
        assert [s.page for s in segments] == [1, 2, 3]

    def test_lossless_against_parse_when_no_blank_page(self, monkeypatch):
        _install_stub_pdf(monkeypatch, ["第一页内容", "第二页内容"])

        assert DocumentParser.parse("whatever.pdf", "pdf") == _join(
            DocumentParser.parse_segments("whatever.pdf", "pdf")
        )


# ────────────────────────────── .docx ──────────────────────────────

class TestParseDocxSegments:
    @pytest.fixture
    def docx_path(self, tmp_path):
        docx = pytest.importorskip("docx")
        document = docx.Document()
        document.add_paragraph("前置正文")
        document.add_heading("第一章", level=1)
        document.add_paragraph("第一章正文")
        document.add_heading("1.1 小节", level=2)
        document.add_paragraph("小节正文")
        document.add_heading("第二章", level=1)
        document.add_paragraph("第二章正文")
        path = tmp_path / "doc.docx"
        document.save(str(path))
        return str(path)

    def test_heading_path_from_style_name(self, docx_path):
        """标题层级取自段落样式名（``Heading N``）这一明确信号"""
        segments = DocumentParser.parse_segments(docx_path, "docx")

        assert [s.heading_path for s in segments] == [
            None,
            "第一章",
            "第一章 > 1.1 小节",
            "第二章",
        ]

    def test_page_is_always_none(self, docx_path):
        """DOCX 无固定分页：同一段落换台机器就换页，不得写页码"""
        assert all(
            s.page is None for s in DocumentParser.parse_segments(docx_path, "docx")
        )

    def test_empty_paragraphs_skipped(self, tmp_path):
        """空段落与 ``parse_docx`` 保持一致地过滤，保证无损契约成立"""
        docx = pytest.importorskip("docx")
        document = docx.Document()
        document.add_paragraph("甲")
        document.add_paragraph("   ")
        document.add_paragraph("乙")
        path = tmp_path / "blank.docx"
        document.save(str(path))

        segments = DocumentParser.parse_segments(str(path), "docx")

        assert len(segments) == 1
        assert segments[0].text == "甲\n乙"

    def test_lossless_against_parse(self, docx_path):
        assert DocumentParser.parse(docx_path, "docx") == _join(
            DocumentParser.parse_segments(docx_path, "docx")
        )


# ─────────────────────── 段内分块（split_segments） ───────────────────────

def _long_text(marker: str, sentences: int = 120) -> str:
    return "".join(f"{marker}第{i}句内容用于撑开分块边界。" for i in range(sentences))


class TestSplitSegments:
    def test_metadata_propagates_and_index_is_global(self):
        """每个块继承所属段的元数据；``index`` 是跨段连续的文档内全局序号"""
        segments = [
            TextSegment(_long_text("甲"), page=3),
            TextSegment(_long_text("乙"), page=7),
        ]

        chunks = TextSplitter(chunk_size=200, chunk_overlap=20).split_segments(segments)

        assert len(chunks) > 2, "文本不足以产生跨段多块，用例前提不成立"
        assert [c.index for c in chunks] == list(range(len(chunks)))
        # 甲段的块页码全为 3，乙段的块页码全为 7——顺序与段一致
        pages = [c.page for c in chunks]
        assert pages == sorted(pages)
        assert pages[0] == 3 and pages[-1] == 7
        assert set(pages) == {3, 7}

    def test_chunk_never_crosses_segment_boundary(self):
        """块边界不得跨越段边界：否则页码归属退化为「起始页」这一近似值"""
        segments = [
            TextSegment("甲段独有标记AAA。" + _long_text("甲"), page=1),
            TextSegment("乙段独有标记BBB。" + _long_text("乙"), page=2),
        ]

        chunks = TextSplitter(chunk_size=200, chunk_overlap=20).split_segments(segments)

        for chunk in chunks:
            if chunk.page == 1:
                assert "乙段独有标记BBB" not in chunk.text
            else:
                assert "甲段独有标记AAA" not in chunk.text

    def test_heading_path_propagates_from_markdown(self, tmp_path):
        """端到端：解析得到的 ``heading_path`` 必须原样落到每个块上"""
        path = tmp_path / "doc.md"
        path.write_text("# 顶层\n" + _long_text("甲", 60) + "\n## 子节\n" + _long_text("乙", 60), encoding="utf-8")

        segments = DocumentParser.parse_segments(str(path), "md")
        chunks = TextSplitter(chunk_size=200, chunk_overlap=20).split_segments(segments)

        assert len(chunks) > 2
        assert all(c.heading_path in {"顶层", "顶层 > 子节"} for c in chunks)
        assert {"顶层", "顶层 > 子节"} <= {c.heading_path for c in chunks}
        # 每个块的标题路径必须与其所属段一致
        by_index = {s.heading_path for s in segments}
        assert {c.heading_path for c in chunks} <= by_index

    def test_empty_and_whitespace_segments_produce_no_chunk(self):
        """空段（如纯空白页）不产出块——否则会出现空内容被向量化"""
        segments = [
            TextSegment(""),
            TextSegment("   \n  "),
            TextSegment("有内容的段"),
        ]

        chunks = TextSplitter(chunk_size=200, chunk_overlap=20).split_segments(segments)

        assert len(chunks) == 1
        assert chunks[0].text == "有内容的段"
        assert chunks[0].index == 0

    def test_each_chunk_is_substring_of_its_own_segment(self):
        """每个块必须是**其所属段**的连续子串——内容不得跨段拼凑或改写"""
        segments = [
            TextSegment(_long_text("甲"), page=1),
            TextSegment(_long_text("乙"), page=2),
        ]

        chunks = TextSplitter(chunk_size=200, chunk_overlap=20).split_segments(segments)

        for chunk in chunks:
            owner = segments[chunk.page - 1]
            assert chunk.text in owner.text

    def test_empty_input_returns_empty_list(self):
        assert TextSplitter().split_segments([]) == []

    def test_split_segments_agrees_with_split_for_single_segment(self):
        """单段输入下，``split_segments`` 的文本序列应与 ``split`` 完全一致"""
        text = _long_text("甲")
        splitter = TextSplitter(chunk_size=200, chunk_overlap=20)

        via_split = splitter.split(text)
        via_segments = [c.text for c in splitter.split_segments([TextSegment(text)])]

        assert via_segments == via_split

    def test_text_chunk_dataclass_defaults(self):
        """``TextChunk`` 的元数据字段可缺省，便于纯文本场景"""
        chunk = TextChunk(text="内容", index=0)

        assert chunk.page is None and chunk.heading_path is None
