"""分段解析与段内分块单测

本文件守住两条契约：

1. **元数据契约**——每段的 ``page`` / ``heading_path`` 要么精确，要么为 ``None``。
   不得用字号、加粗、位置等启发式把猜测写进「出处」字段：``source_page`` /
   ``heading_path`` 是给人核对出处用的，写错比留空更糟。
2. **文本契约**——``\\n\\n`` 是结构边界，``\\n`` 是同一结构单元内的换行；四种格式的
   解析结果都必须满足它，否则分块器（其分隔符链第一级就是 ``"\\n\\n"``）只能退化到
   句号、逗号一级，块边界随之落在任意位置。

关于「无损契约」的历史与现状
----------------------------
旧版本文件要求 ``DocumentParser.parse()`` **逐字符**等于
``"\\n".join(s.text for s in parse_segments())``，即分段只是把同一份文本切开、不增删
任何字符。PDF 段落重建必然打破它——重建要剔除页码/页眉等噪声行、并合并被折行截断的
行（实测 310 页的 ``\\n\\n`` 因此从 0 涨到 2900，块尾「切断句子」的比例从 60.5% 降到
5.8%）。故契约改为三条更弱但**可证伪**的断言：

a. ``parse()`` 由 ``parse_segments()`` **派生**，两者永远一致（不留第二份实现）；
b. 归一化只做结构变换：除噪声行外内容按原顺序保留（由
   ``tests/test_text_structure.py`` 的 ``test_content_order_preserved`` + 本文件的
   逐格式断言共同覆盖）；
c. 归一化是**确定性**的。

分块侧另守两条（P2 结构组合并后的新契约）：

d. 块在**结构组内**进行切分，组由「顶层标题硬边界 + 短串并入下一串」确定；块因此
   **可以跨段、跨页、跨小节**——这是消除碎片块的必然代价，由 ``page``/``page_end``
   区间与 ``heading_path_mixed`` 如实记录，不再退化为一个近似值；
e. 每个块仍是其所属结构组文本的**连续子串**，页码区间必须覆盖块内出现的每一页。
"""

import sys
import types

import pytest

from app.utils.document import (
    DocumentParser,
    TextChunk,
    TextSegment,
    TextSplitter,
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

    def test_blank_lines_are_the_structural_boundary(self, tmp_path):
        """txt 原文即契约：空行就是段落边界，解析层必须原样保留"""
        path = tmp_path / "a.txt"
        path.write_text("甲段内容。\n\n乙段内容。", encoding="utf-8")

        segments = DocumentParser.parse_segments(str(path), "txt")

        assert "\n\n" in segments[0].text

    def test_parse_derives_from_segments(self, tmp_path):
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
        """空行必须保留：它就是段落边界（``\\n\\n``），丢了分块器就没法按段落落刀"""
        path = tmp_path / "doc.md"
        content = "# A\n\n正文\n\n\n尾部"
        path.write_text(content, encoding="utf-8")

        assert DocumentParser.parse(str(path), "md") == _join(
            DocumentParser.parse_segments(str(path), "md")
        )
        assert "\n\n" in DocumentParser.parse(str(path), "md")

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

    def test_hash_inside_fenced_code_is_not_a_heading(self, tmp_path):
        """围栏代码块内的 ``#`` 不是标题

        旧实现逐行匹配 ATX 标题且不维护围栏状态，于是 shell 片段里的注释行
        （``# 安装依赖``）会被当成章节标题并**在此切断分段**：凭空造出一个不存在的
        章节、给代码块的后半段挂上一个伪装标题，且代码块被劈成两段。
        """
        path = tmp_path / "doc.md"
        path.write_text(
            "# 顶层\n\n"
            "```bash\n"
            "# 安装依赖\n"
            "pip install x\n"
            "```\n\n"
            "## 子节\n正文\n",
            encoding="utf-8",
        )

        segments = DocumentParser.parse_segments(str(path), "md")

        # 围栏内的 ``#`` 不造标题：代码块作为独立原子块（S4），且内部文本不被当标题。
        code = [s for s in segments if s.kind == "code"]
        assert code, "代码块应作为独立原子块"
        assert "# 安装依赖" in code[0].text
        assert code[0].is_atomic
        assert not any(s.kind == "heading" and "安装依赖" in s.text for s in segments)
        # 标题层级仍正确（代码块不干扰 heading_path 栈）
        heading_paths = [s.heading_path for s in segments if s.kind == "heading"]
        assert heading_paths == ["顶层", "顶层 > 子节"]

    def test_tilde_fence_also_protects(self, tmp_path):
        """``~~~`` 与 ````` ``` ````` 同为合法围栏；围栏内容作为独立代码块"""
        path = tmp_path / "doc.md"
        path.write_text("# A\n~~~\n# 注释\n~~~\n正文\n", encoding="utf-8")

        segments = DocumentParser.parse_segments(str(path), "md")

        code = [s for s in segments if s.kind == "code"]
        assert code, "代码块应作为独立原子块"
        assert "# 注释" in code[0].text
        assert code[0].is_atomic
        assert not any(s.kind == "heading" and "注释" in s.text for s in segments)
        assert all(s.heading_path in (None, "A") for s in segments)

    def test_longer_fence_swallows_shorter_marker(self, tmp_path):
        """````` `````  内部出现的三反引号不构成闭合——闭合标记须不短于开启标记"""
        path = tmp_path / "doc.md"
        path.write_text("# A\n````\n# 内部\n```\n# 仍在围栏内\n````\n正文\n", encoding="utf-8")

        segments = DocumentParser.parse_segments(str(path), "md")

        code = [s for s in segments if s.kind == "code"]
        assert code, "代码块应作为独立原子块"
        assert "# 内部" in code[0].text and "# 仍在围栏内" in code[0].text
        assert not any(
            s.kind == "heading" and ("内部" in s.text or "仍在围栏内" in s.text)
            for s in segments
        )

    def test_parse_derives_from_segments(self, tmp_path):
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
    """桩页：默认模式返回整页文本，visitor 模式按行回放片段

    两个通道都要支持，因为解析层是**双通道**的：文本取自默认模式（与现状逐字符
    一致），版式信号取自 ``visitor_text``。桩若不支持 ``visitor_text``，
    「标题识别」这条契约就完全无法覆盖。

    ``sizes`` / ``fonts`` 按**非空行**的下标给出，缺省正文 10.0 / 常规字体。
    回调里刻意把 ``font_size`` 传 1.0、把真实字号放进 ``tm`` 的缩放位——这正是
    真实 PDF 的行为（内容流用 ``Tf`` 设 1 倍），桩若照抄直觉反而测不出这条契约。
    """

    def __init__(self, text, sizes=None, fonts=None):
        self._text = text or ""
        self._sizes = sizes or []
        self._fonts = fonts or []

    def extract_text(self, visitor_text=None):
        if visitor_text is None:
            return self._text
        y = 700.0
        for index, line in enumerate([l for l in self._text.split("\n") if l.strip()]):
            size = self._sizes[index] if index < len(self._sizes) else 10.0
            font = self._fonts[index] if index < len(self._fonts) else "X-Regular"
            visitor_text(
                line, None, [size, 0.0, 0.0, size, 10.0, y],
                {"/BaseFont": font}, 1.0,
            )
            y -= size * 1.5
        return self._text


def _make_page(spec):
    if isinstance(spec, tuple):
        text, sizes = spec[0], spec[1]
        fonts = spec[2] if len(spec) > 2 else None
        return _StubPage(text, sizes=sizes, fonts=fonts)
    return _StubPage(spec)


def _install_stub_pdf(monkeypatch, pages_text):
    """把假的 ``pypdf`` 注入 ``sys.modules``，使解析无需真实 PDF 文件"""
    module = types.ModuleType("pypdf")

    class _StubReader:
        def __init__(self, _path):
            self.pages = [_make_page(t) for t in pages_text]

    module.PdfReader = _StubReader
    monkeypatch.setitem(sys.modules, "pypdf", module)
    return module


class TestParsePdfSegments:
    def test_segment_page_is_one_based_and_content_preserved(self, monkeypatch):
        """页码为 1 基（与阅读器显示一致）；段 = 一节，页边界是硬边界"""
        _install_stub_pdf(monkeypatch, ["第1页正文。", "第2页正文。"])

        segments = DocumentParser.parse_segments("whatever.pdf", "pdf")

        assert [s.text for s in segments] == ["第1页正文。", "第2页正文。"]
        assert [s.page for s in segments] == [1, 2]

    def test_wrapped_lines_are_merged_into_paragraphs(self, monkeypatch):
        """版面折行必须被合并：这是「块边界落在句子中间」的根因所在

        未合并时，段内折行与段落边界同为 ``\\n``，分块器只能按行装箱，
        82.5% / 87.2% 的块尾落在句子中间。
        """
        _install_stub_pdf(
            monkeypatch,
            ["第一句没有句末标点\n续写同一段结束。\n第二段开始"],
        )

        segments = DocumentParser.parse_segments("whatever.pdf", "pdf")

        assert segments[0].text == "第一句没有句末标点续写同一段结束。\n\n第二段开始"

    def test_double_newline_becomes_reachable(self, monkeypatch):
        """段落重建的目的：让分块器的第一级分隔符 ``"\\n\\n"`` 在 PDF 上可达

        改造前实测 310 页 ``\\n\\n`` 出现 0 次（全部 310 段命中第二级 ``\\n``），
        分块因此退化为「按版面行装箱」。
        """
        _install_stub_pdf(
            monkeypatch, ["第一句。\n第二句。\n第三句。", "第四句。\n第五句。"]
        )

        segments = DocumentParser.parse_segments("whatever.pdf", "pdf")

        assert all("\n\n" in s.text for s in segments)

    def test_page_number_only_line_dropped(self, monkeypatch):
        """只含页码的行不是正文，且它同时是一个结构断点"""
        _install_stub_pdf(monkeypatch, ["上文内容。\n12\n下文内容。"])

        segments = DocumentParser.parse_segments("whatever.pdf", "pdf")

        assert segments[0].text == "上文内容。\n\n下文内容。"

    def test_running_header_dropped_across_pages(self, monkeypatch):
        """跨页重复的页眉是版面装饰，实测它会被检索命中并污染词频"""
        pages = [f"AI Studio 手册\n第 {i} 章的正文内容。" for i in range(1, 9)]
        _install_stub_pdf(monkeypatch, pages)

        segments = DocumentParser.parse_segments("whatever.pdf", "pdf")

        assert all("用户手册" not in s.text and "AI Studio 手册" not in s.text for s in segments)
        assert len(segments) == 8

    def test_heading_path_is_derived_from_font_size(self, monkeypatch):
        """PDF 的标题路径由版式信号识别（**推翻**旧的「恒为 None」契约）

        旧契约的理由是「pypdf 只给文本流，据字号推断标题属于猜测」。该前提已不成立
        ——``visitor_text`` 回调给出字号/字体/坐标，故改为「多信号加权过阈值才判标题、
        取不到信号的行一律按普通段落处理」，并以真实 PDF 的抽样人工核对作验收。
        """
        body = "正文内容用于撑长度。" * 20
        _install_stub_pdf(
            monkeypatch,
            [("第 1 章 入门\n" + body, [15.0, 10.0])],
        )

        segments = DocumentParser.parse_segments("whatever.pdf", "pdf")

        assert segments[0].heading_path == "第 1 章 入门"
        assert segments[0].text.startswith("第 1 章 入门")

    def test_plain_body_without_size_signal_yields_no_heading_path(self, monkeypatch):
        """字号全是正文 ⇒ 不得凭空造出标题（保守回落的守卫用例）"""
        _install_stub_pdf(monkeypatch, [("普通正文一段。\n普通正文两段。", [10.0, 10.0])])

        segments = DocumentParser.parse_segments("whatever.pdf", "pdf")

        assert all(s.heading_path is None for s in segments)

    def test_blank_page_produces_no_segment_and_pages_stay_correct(self, monkeypatch):
        """空白页不产出段，但**后续页码不会错位**

        旧实现必须保留空段占位，因为页码来自 ``enumerate`` 的下标——一旦过滤掉
        空页，之后所有页码都会前移。新实现的页码由每段的 ``page`` **显式携带**，
        故占位不再必要；这条用例正是守护该性质。
        """
        _install_stub_pdf(monkeypatch, ["第1页内容。", None, "", "第4页内容。"])

        segments = DocumentParser.parse_segments("whatever.pdf", "pdf")

        assert [s.text for s in segments] == ["第1页内容。", "第4页内容。"]
        assert [s.page for s in segments] == [1, 4]

    def test_parse_derives_from_segments(self, monkeypatch):
        _install_stub_pdf(monkeypatch, ["第一页内容。", "第二页内容。"])

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

    def test_heading_bound_to_body_without_blank_line(self, docx_path):
        """标题与其正文之间用单个 ``\\n``

        若用空行，``\\n\\n`` 就成了分块器的最高优先级切点，长小节会切出「只有标题」
        的孤儿块（社区 ``chunk_by_title`` 明确禁止的行为）。
        """
        segments = DocumentParser.parse_segments(docx_path, "docx")

        assert segments[1].text == "第一章\n第一章正文"

    def test_sibling_paragraphs_separated_by_blank_line(self, tmp_path):
        """同级段落之间用空行（``\\n\\n``），使结构边界对分块器可见

        旧实现一律用单个 ``\\n`` 连接，导致段落、列表项、标题三者不可区分，
        且分块器第一级分隔符永远命不中。
        """
        docx = pytest.importorskip("docx")
        document = docx.Document()
        document.add_heading("章标题", level=1)
        document.add_paragraph("第一段正文。")
        document.add_paragraph("第二段正文。")
        path = tmp_path / "paras.docx"
        document.save(str(path))

        segments = DocumentParser.parse_segments(str(path), "docx")

        assert segments[0].text == "章标题\n第一段正文。\n\n第二段正文。"
        assert "\n\n" in segments[0].text

    def test_each_heading_opens_its_own_segment(self, tmp_path):
        """标题总是开启新的一段——因此空节会产出「只有标题」的段

        这是**预期行为**，不能靠解析层消除：标题必须独立成段才能携带 ``heading_path``
        （块的出处信息）。空节产生的孤儿块由分块层的「结构组合并」处理（把过短的
        结构组并入相邻组）。本用例把该行为固定下来，避免误以为解析层已经解决它。
        """
        docx = pytest.importorskip("docx")
        document = docx.Document()
        document.add_heading("第一章", level=1)
        document.add_heading("1.1 空节", level=2)
        document.add_heading("1.2 有内容", level=2)
        document.add_paragraph("正文。")
        path = tmp_path / "empty.docx"
        document.save(str(path))

        segments = DocumentParser.parse_segments(str(path), "docx")

        assert [s.text for s in segments] == ["第一章", "1.1 空节", "1.2 有内容\n正文。"]
        assert [s.heading_path for s in segments] == [
            "第一章",
            "第一章 > 1.1 空节",
            "第一章 > 1.2 有内容",
        ]

    def test_empty_paragraphs_skipped(self, tmp_path):
        """空段落不承载内容，保留只会产生连续空行"""
        docx = pytest.importorskip("docx")
        document = docx.Document()
        document.add_paragraph("甲")
        document.add_paragraph("   ")
        document.add_paragraph("乙")
        path = tmp_path / "blank.docx"
        document.save(str(path))

        segments = DocumentParser.parse_segments(str(path), "docx")

        assert len(segments) == 1
        assert segments[0].text == "甲\n\n乙"

    def test_parse_derives_from_segments(self, docx_path):
        assert DocumentParser.parse(docx_path, "docx") == _join(
            DocumentParser.parse_segments(docx_path, "docx")
        )


# ────────────────────── 文本契约（跨格式） ──────────────────────

class TestTextContractAcrossFormats:
    """四种格式都必须满足：``\\n\\n`` 是可达的结构边界

    这是解析层与分块层之间唯一的约定；它是「块边界落在文档结构边缘」的**充分前提**
    （分块器把 ``"\\n\\n"`` 用作分隔符链的第一级）。四种格式的历史达成情况差异极大：

    * txt / md：原文即契约，无需处理；
    * docx：旧实现用单个 ``\\n`` 连接段落，``\\n\\n`` 恒为 0；
    * pdf：旧实现输出的是版面行流，实测 310 页 ``\\n\\n`` 出现 **0 次**。
    """

    def test_docx_makes_double_newline_reachable(self, tmp_path):
        docx = pytest.importorskip("docx")
        document = docx.Document()
        document.add_paragraph("第一段。")
        document.add_paragraph("第二段。")
        path = tmp_path / "c.docx"
        document.save(str(path))

        text = DocumentParser.parse(str(path), "docx")

        assert "\n\n" in text

    def test_unknown_format_rejected(self, tmp_path):
        with pytest.raises(ValueError):
            DocumentParser.parse_segments(str(tmp_path / "a.rtf"), "rtf")


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

    def test_chunk_page_range_covers_every_page_it_spans(self):
        """跨页合并在新契约下是**允许**的；不变量改为「页码区间如实覆盖」

        旧契约是「块不得跨越段边界」，但跨页/跨小节合并正是本次改造的目标，段边界
        不再是硬块边界。真正必须守住的不变量是：``[page, page_end]`` 必须覆盖块文本
        中出现的**每一页**的内容，否则前端展示的出处就是错的。
        """
        segments = [
            TextSegment("甲段独有标记AAA。" + _long_text("甲"), page=1),
            TextSegment("乙段独有标记BBB。" + _long_text("乙"), page=2),
        ]

        chunks = TextSplitter(chunk_size=200, chunk_overlap=20).split_segments(segments)

        assert len(chunks) > 2, "用例前提不成立"
        for chunk in chunks:
            assert chunk.page is not None and chunk.page_end is not None
            assert chunk.page <= chunk.page_end
            if "甲段独有标记AAA" in chunk.text:
                assert chunk.page <= 1 <= chunk.page_end
            if "乙段独有标记BBB" in chunk.text:
                assert chunk.page <= 2 <= chunk.page_end
        # 首页内容开篇、末页内容收尾，区间随内容单调推进
        assert chunks[0].page == 1
        assert chunks[-1].page_end == 2

    def test_heading_path_propagates_from_markdown(self, tmp_path):
        """端到端：解析得到的 ``heading_path`` 必须原样落到每个块上

        合并父节与其子节时 ``heading_path`` **收敛为公共前缀**（此处为 ``顶层``）：
        块确实同时属于父节与子节，标注父节是精确的，故不标 ``mixed``。
        """
        path = tmp_path / "doc.md"
        path.write_text("# 顶层\n" + _long_text("甲", 60) + "\n## 子节\n" + _long_text("乙", 60), encoding="utf-8")

        segments = DocumentParser.parse_segments(str(path), "md")
        chunks = TextSplitter(chunk_size=200, chunk_overlap=20).split_segments(segments)

        assert len(chunks) > 2
        assert {c.heading_path for c in chunks} == {"顶层"}
        assert all(c.heading_path_mixed is False for c in chunks)

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

    def test_each_chunk_is_a_contiguous_substring_of_group_text(self):
        """每个块必须是**其所属结构组文本**的连续子串——内容不得跨组拼凑或改写

        组文本 = 组内各段以 ``\\n\\n`` 连接。块可以跨段（合并的必然结果），但必须在
        原文本里连续，否则页码区间与偏移定位全部失真。
        """
        segments = [
            TextSegment(_long_text("甲"), page=1),
            TextSegment(_long_text("乙"), page=2),
        ]
        splitter = TextSplitter(chunk_size=200, chunk_overlap=20)
        group_texts = [text for _group, text in splitter.iter_group_texts(segments)]

        chunks = splitter.split_segments(segments)

        assert len(chunks) > 2, "用例前提不成立"
        for chunk in chunks:
            assert any(chunk.text in group_text for group_text in group_texts), (
                f"块不在任何组文本中：{chunk.text[:40]!r}"
            )

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

    def test_paragraph_boundary_is_preferred_over_line_break(self):
        """段落边界优先于行内换行：有 ``\\n\\n`` 可选时不得退化为按 ``\\n`` 切

        这是「块边界落在结构边缘」在分块器一侧的体现。构造一份段落清晰、且每段都
        不足 ``chunk_size`` 的文本：分块器应把整段并入同一块，而不是在段内换行处切开。
        """
        paragraph = "这是一段完整的段落内容，长度不足以触发尺寸拆分。" * 3
        text = f"{paragraph}\n\n{paragraph}\n\n{paragraph}"
        splitter = TextSplitter(chunk_size=200, chunk_overlap=20)

        chunks = splitter.split(text)

        assert chunks, "用例前提不成立"
        for chunk in chunks:
            # 每个块的结尾都必须是某个段落的结尾，而不是段落中间的某个换行
            assert text.count(chunk.strip()) >= 1
            assert chunk.strip().endswith("。")


# ─────────────────── 结构组合并（P2：碎片消除 + 元数据区间化） ───────────────────

#: 用例统一使用的块参数。``min_fill_chars`` 缺省 = ``int(200 × 0.5)`` = 100。
_SMALL = {"chunk_size": 200, "chunk_overlap": 20}


def _group_texts(segments, **kwargs) -> list:
    """按分块器**同源**的分组视图取组文本"""
    splitter = TextSplitter(**{**_SMALL, **kwargs})
    return [text for _group, text in splitter.iter_group_texts(segments)]


class TestStructuralGrouping:
    """结构组的分组规则（``_mergeable_runs`` + ``_combine_undersized``）

    分组是「块边界能否落在结构边缘」的上游：分错了组，后面无论怎么切都落在错的边界上。
    这些用例锁定两条规则——**顶层标题是串内硬边界**、**长度不达标的串并入下一串**。
    """

    def test_heading_is_absorbed_into_its_body(self):
        """标题行（顶层）必须与其正文同组

        标题行自身的 ``heading_path`` 与其正文相同（深度均为 1），故
        :meth:`TextSplitter._can_merge` **不会**把它并进正文串——它靠「短串并入
        下一串」被吸收。若只看硬边界规则就下结论，会误以为标题与正文被拆开了。
        """
        segments = [
            TextSegment("# 顶层\n", heading_path="顶层"),
            TextSegment("正文内容用于撑长度。" * 15, heading_path="顶层"),
        ]

        splitter = TextSplitter(**_SMALL)
        groups = [g for g, _t in splitter.iter_group_texts(segments)]
        chunks = splitter.split_segments(segments)

        assert len(groups) == 1, "标题行应被并入其正文所在的串"
        assert chunks[0].text.startswith("# 顶层")
        assert {c.heading_path for c in chunks} == {"顶层"}
        assert all(c.heading_path_mixed is False for c in chunks)

    def test_parent_and_child_sections_share_one_group(self):
        """父节与其子节同组：路径收敛为父节，且**不**标记 ``mixed``

        ``{A, A > B}`` 的公共前缀 ``A`` 就在集合里，标注 ``A`` 是精确的——块确实含
        A 自身的内容。旧实现按「路径数 > 1」判定，会把它误标为 ``mixed``。
        """
        segments = [
            TextSegment("# A\n", heading_path="A"),
            TextSegment("甲" * 20, heading_path="A"),
            TextSegment("## B\n", heading_path="A > B"),
            TextSegment("乙" * 20, heading_path="A > B"),
        ]

        splitter = TextSplitter(**_SMALL)
        chunks = splitter.split_segments(segments)

        assert {c.heading_path for c in chunks} == {"A"}
        assert all(c.heading_path_mixed is False for c in chunks)

    def test_sibling_subsections_only_yield_common_ancestor_and_mark_mixed(self):
        """只含兄弟子节时，公共前缀**粗于**实际覆盖范围，必须标 ``mixed``"""
        segments = [
            TextSegment("## B\n", heading_path="A > B"),
            TextSegment("乙" * 20, heading_path="A > B"),
            TextSegment("## C\n", heading_path="A > C"),
            TextSegment("丙" * 20, heading_path="A > C"),
        ]

        splitter = TextSplitter(**_SMALL)
        chunks = splitter.split_segments(segments)

        assert {c.heading_path for c in chunks} == {"A"}
        assert all(c.heading_path_mixed is True for c in chunks), (
            "块只含 B、C 的内容，却只能标注 A，必须如实标记为粗化"
        )

    def test_undersized_section_combines_with_next_section(self):
        """短小节并入下一小节，而不是独占一个半空块

        这是 :data:`GROUP_MIN_FILL_RATIO` 存在的理由，也是社区
        ``chunk_by_title`` 的 ``combine_text_under_n_chars`` 语义。
        """
        segments = [
            TextSegment("# 短节\n", heading_path="短节"),
            TextSegment("短节正文。" * 8, heading_path="短节"),
            TextSegment("# 长节\n", heading_path="长节"),
            TextSegment("长节正文。" * 30, heading_path="长节"),
        ]

        splitter = TextSplitter(**_SMALL)
        groups = [g for g, _t in splitter.iter_group_texts(segments)]
        chunks = splitter.split_segments(segments)

        assert len(groups) == 1, "两节应合成一串后再按尺寸切分"
        assert "短节正文" in chunks[0].text
        assert {c.heading_path for c in chunks} == {None}, "跨顶层小节的块不得谎报章节名"
        assert all(c.heading_path_mixed is True for c in chunks)

    def test_min_fill_zero_keeps_sections_separate(self):
        """``min_fill_chars=0`` 关闭合并：用于 A/B 对比与回归定位

        关闭后短小节独立成块（旧行为），可用来证明「指标变化确实来自合并」而不是
        其他改动的副作用。
        """
        segments = [
            TextSegment("# 短节\n", heading_path="短节"),
            TextSegment("短节正文。" * 8, heading_path="短节"),
            TextSegment("# 长节\n", heading_path="长节"),
            TextSegment("长节正文。" * 30, heading_path="长节"),
        ]

        splitter = TextSplitter(**_SMALL, min_fill_chars=0)
        groups = [g for g, _t in splitter.iter_group_texts(segments)]
        chunks = splitter.split_segments(segments)

        assert len(groups) == 4, "关闭合并后每个可合并串独立成组"
        assert len(chunks) == 4
        assert {c.heading_path for c in chunks} == {"短节", "长节"}

    def test_long_sibling_sections_are_never_merged(self):
        """两个**都不短**的顶层小节必须各自成块：硬边界不得被尺寸策略架空"""
        segments = [
            TextSegment("# A\n", heading_path="A"),
            TextSegment("甲节正文。" * 60, heading_path="A"),
            TextSegment("# B\n", heading_path="B"),
            TextSegment("乙节正文。" * 60, heading_path="B"),
        ]

        splitter = TextSplitter(**_SMALL)
        groups = [g for g, _t in splitter.iter_group_texts(segments)]
        chunks = splitter.split_segments(segments)

        assert len(groups) == 2
        assert {c.heading_path for c in chunks} == {"A", "B"}
        assert all(not ("甲" in c.text and "乙" in c.text) for c in chunks)

    def test_trailing_undersized_section_merges_backward(self):
        """文档末尾的短小节没有「下一串」可并，应并入前一组"""
        segments = [
            TextSegment("# A\n", heading_path="A"),
            TextSegment("甲节正文。" * 30, heading_path="A"),
            TextSegment("# B\n", heading_path="B"),
        ]

        splitter = TextSplitter(**_SMALL)
        groups = [g for g, _t in splitter.iter_group_texts(segments)]
        chunks = splitter.split_segments(segments)

        assert len(groups) == 1
        assert "# B" in chunks[0].text, "末尾短小节应并入前一组而不是独立成块"
        assert chunks[0].heading_path is None

    def test_no_heading_segments_merge_freely_across_pages(self):
        """无标题结构的格式（PDF / TXT）跨页自由合并，页码由区间记录"""
        segments = [
            TextSegment("甲页正文。" * 20, page=1),
            TextSegment("乙页正文。" * 20, page=2),
        ]

        splitter = TextSplitter(**_SMALL)
        groups = [g for g, _t in splitter.iter_group_texts(segments)]
        chunks = splitter.split_segments(segments)

        assert len(groups) == 1, "PDF 无标题边界，应合成一串"
        assert chunks[0].page == 1
        assert chunks[-1].page_end == 2
        for chunk in chunks:
            assert chunk.page <= chunk.page_end
            if "甲" in chunk.text:
                assert chunk.page <= 1 <= chunk.page_end
            if "乙" in chunk.text:
                assert chunk.page <= 2 <= chunk.page_end

    def test_very_large_min_fill_never_truncates_content(self):
        """把 ``min_fill_chars`` 拉到极大只会「全并成一串」，不得丢内容

        守住两端：首块从组文本开头起，末块接到组文本结尾。中间的重叠是刻意保留的，
        故这里只断言边界，不断言逐字符相等。
        """
        segments = [
            TextSegment("# A\n", heading_path="A"),
            TextSegment("甲节正文。" * 30, heading_path="A"),
            TextSegment("# B\n", heading_path="B"),
            TextSegment("乙节正文。" * 30, heading_path="B"),
        ]

        splitter = TextSplitter(**_SMALL, min_fill_chars=10**9)
        groups = [g for g, _t in splitter.iter_group_texts(segments)]
        chunks = splitter.split_segments(segments)
        group_text = "\n\n".join(s.text for s in segments)

        assert len(groups) == 1
        assert group_text.rstrip().startswith(chunks[0].text)
        assert group_text.rstrip().endswith(chunks[-1].text)

    def test_grouping_is_deterministic(self):
        """同输入必须同输出——``index`` 参与 ``vector_id`` 推导，不可漂移"""
        segments = [
            TextSegment("# A\n", heading_path="A"),
            TextSegment("甲节正文。" * 30, heading_path="A"),
            TextSegment("# B\n", heading_path="B"),
            TextSegment("乙节正文。" * 30, heading_path="B"),
        ]
        splitter = TextSplitter(**_SMALL)

        first = splitter.split_segments(segments)
        second = splitter.split_segments(segments)

        assert [(c.index, c.text, c.heading_path, c.page_end) for c in first] == [
            (c.index, c.text, c.heading_path, c.page_end) for c in second
        ]


class TestPageRangeLookup:
    """``_segment_bounds`` / ``_page_range``：块 -> 页码区间的同源映射

    组内偏移与块偏移同源（都源自 ``"\\n\\n".join(段文本)``），故页码绝不会与内容错位。
    这里直接对纯函数下断言，避免只在端到端用例里间接覆盖。
    """

    #: 「aaa」+「\\n\\n」+「bbbb」+「\\n\\n」+「cc」的段边界表
    BOUNDS = [
        (0, 3, 1),
        (5, 9, 2),
        (11, 13, 3),
    ]

    def test_segment_bounds_offsets(self):
        bounds = TextSplitter._segment_bounds(
            [
                TextSegment("aaa", page=1),
                TextSegment("bbbb", page=2),
                TextSegment("cc", page=3),
            ]
        )
        assert bounds == self.BOUNDS

    def test_page_range_within_single_segment(self):
        assert TextSplitter._page_range(self.BOUNDS, 0, 3, 0) == (1, 1, 1)

    def test_page_range_skips_segment_ending_exactly_at_start(self):
        """块的起点恰在段尾时，该段不贡献页码（否则区间会向左多算一页）"""
        assert TextSplitter._page_range(self.BOUNDS, 3, 9, 0) == (2, 2, 2)

    def test_page_range_resumes_from_cursor(self):
        assert TextSplitter._page_range(self.BOUNDS, 9, 13, 1) == (3, 3, 3)

    def test_page_range_returns_advanced_cursor(self):
        """返回值必须是扫描后的游标，后续块才能保持线性扫描"""
        assert TextSplitter._page_range(self.BOUNDS, 3, 13, 0) == (2, 3, 3)

    def test_page_range_spans_whole_group(self):
        assert TextSplitter._page_range(self.BOUNDS, 0, 14, 0) == (1, 3, 3)

    def test_page_range_without_pages_returns_none(self):
        bounds = TextSplitter._segment_bounds([TextSegment("甲"), TextSegment("乙")])
        assert TextSplitter._page_range(bounds, 0, 5, 0) == (None, None, 2)

    def test_repeated_chunk_text_keeps_later_page_attribution(self):
        """相同文本跨页出现时，后一个块不能再次定位到第一次出现的位置"""
        segments = [
            TextSegment("abc", page=1),
            TextSegment("abc", page=2),
        ]

        chunks = TextSplitter(chunk_size=3, chunk_overlap=0).split_segments(segments)

        assert [chunk.text for chunk in chunks] == ["abc", "abc"]
        assert [(chunk.page, chunk.page_end) for chunk in chunks] == [(1, 1), (2, 2)]
