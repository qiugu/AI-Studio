"""S3/S4 表格识别的单元测试

覆盖：线框表格检测、无线框（列对齐）表格检测、装饰矩形过滤、GFM 渲染、
PDF 集成（表格文本不重复进入段落流）、MD 管道表、DOCX 表格。

全部用合成数据或本地临时文件，不依赖知识库里的真实 PDF。
"""
from __future__ import annotations

from pathlib import Path

from app.utils import structure_blocks as sb
from app.utils.document import DocumentParser


def frag(page=1, x=100.0, y=700.0, text="x", size=10.0):
    return sb.Fragment(
        page=page, text=text, size=size, font="Helvetica",
        x=x, y=y, bold=False, mono=False,
    )


def hline(y, x0=100.0, x1=400.0, page=1):
    return sb.GeometryLine(x0=x0, y0=y, x1=x1, y1=y, page=page)


def vline(x, y0=700.0, y1=800.0, page=1):
    return sb.GeometryLine(x0=x, y0=y0, x1=x, y1=y1, page=page)


def test_ruled_table_detection():
    """闭合线框网格应被识别为 2×2 表格，并渲染出正确 GFM"""
    geom = [
        hline(800), hline(750), hline(700),
        vline(100), vline(250), vline(400),
    ]
    frags = [
        frag(x=175, y=775, text="Alpha"),
        frag(x=325, y=775, text="Beta"),
        frag(x=175, y=725, text="1"),
        frag(x=325, y=725, text="2"),
    ]
    tables = sb.detect_tables(geom, frags, 1)
    assert len(tables) == 1
    t = tables[0]
    assert t.n_rows == 2 and t.n_cols == 2
    assert "Alpha" in t.markdown and "Beta" in t.markdown
    assert "| --- | --- |" in t.markdown
    assert "| 1 | 2 |" in t.markdown


def test_table_text_excluded_from_paragraphs():
    """PDF 集成：表格文本不重复进入段落流，且作为独立 table 块出现"""
    pages = ["Alpha\nBeta\n1\n2\n这是正文段落"]
    frags = [
        frag(x=175, y=775, text="Alpha"),
        frag(x=325, y=775, text="Beta"),
        frag(x=175, y=725, text="1"),
        frag(x=325, y=725, text="2"),
        frag(x=100, y=600, text="这是正文段落"),
    ]
    geom = [hline(800), hline(750), hline(700), vline(100), vline(250), vline(400)]
    blocks = sb.build_blocks(pages, frags, geom)

    table_blocks = [b for b in blocks if b.kind == "table"]
    assert len(table_blocks) == 1
    # 表格文本不应出现在任何段落/标题块里（避免与表格块重复）
    para_text = " ".join(b.text for b in blocks if b.kind in ("paragraph", "heading"))
    assert "Alpha" not in para_text and "1" not in para_text
    # 正文段落仍在
    assert any(b.kind == "paragraph" and "这是正文段落" in b.text for b in blocks)


def test_borderless_table_detection():
    """无线框但列对齐的多行应被识别为表格"""
    frags = []
    for y in (620, 600, 580):
        frags.append(frag(x=100, y=y, text="姓名"))
        frags.append(frag(x=300, y=y, text="年龄"))
    frags.append(frag(x=100, y=560, text="张三"))
    frags.append(frag(x=300, y=560, text="28"))
    tables = sb.detect_tables([], frags, 1)
    assert len(tables) == 1
    assert tables[0].n_cols == 2 and tables[0].n_rows >= 2


def test_decorative_rectangle_ignored():
    """整页背景矩形（无内部网格）不是表格"""
    geom = [
        sb.GeometryLine(0, 0, 595, 0, 1),
        sb.GeometryLine(0, 842, 595, 842, 1),
        sb.GeometryLine(0, 0, 0, 842, 1),
        sb.GeometryLine(595, 0, 595, 842, 1),
    ]
    tables = sb.detect_tables(geom, [], 1)
    assert tables == []


def test_grid_to_markdown_escapes_pipes():
    """单元格内的竖线应被转义，避免破坏 GFM"""
    grid = {(0, 0): "a|b", (0, 1): "c", (1, 0): "1", (1, 1): "2"}
    md = sb._grid_to_markdown(grid, 2, 2)
    assert "a\\|b" in md


def test_md_pipe_table_segment(tmp_path: Path):
    """MD 管道表应作为独立 table 原子块"""
    path = tmp_path / "doc.md"
    path.write_text(
        "# 标题\n\n"
        "| 列A | 列B |\n| --- | --- |\n| 1 | 2 |\n| 3 | 4 |\n\n"
        "结尾正文\n",
        encoding="utf-8",
    )
    segments = DocumentParser.parse_segments(str(path), "md")
    tables = [s for s in segments if s.kind == "table"]
    assert tables, "管道表应被识别为 table 段"
    assert tables[0].is_atomic
    assert "| 列A | 列B |" in tables[0].text
    assert "| 1 | 2 |" in tables[0].text
    # 管道表不污染标题栈：结尾正文仍挂在「标题」下
    para = [s for s in segments if s.kind == "paragraph"]
    assert para and para[0].heading_path == "标题"


def test_docx_table_segment(tmp_path: Path):
    """DOCX 表格（doc.tables）应被识别为 table 原子块，且不丢内容"""
    from docx import Document

    path = tmp_path / "doc.docx"
    doc = Document()
    doc.add_heading("标题", level=1)
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "姓名"
    table.cell(0, 1).text = "年龄"
    table.cell(1, 0).text = "张三"
    table.cell(1, 1).text = "28"
    doc.add_paragraph("结尾正文")
    doc.save(str(path))

    segments = DocumentParser.parse_segments(str(path), "docx")
    tables = [s for s in segments if s.kind == "table"]
    assert tables, "DOCX 表格应被识别为 table 段"
    assert tables[0].is_atomic
    assert "姓名" in tables[0].text and "张三" in tables[0].text
    # 表格内容此前被静默丢弃：现在应出现在某个段里
    all_text = " ".join(s.text for s in segments)
    assert "张三" in all_text


def test_atomic_chunk_not_split():
    """表格/代码原子块在分块层不被切碎（S5）

    前提是**未超 ``ATOMIC_MAX_CHARS``**（默认 `2 × chunk_size`）：超限者会被降级
    切分，因为 `is_atomic` 的「不切碎」承诺与嵌入模型 `max_seq_length=512`
    （中文 ≈476 字）的**静默截断**直接冲突——超出部分从不进入向量。
    降级行为另见 `test_text_splitter.py::TestOversizedAtomicDowngrade`。
    """
    from app.utils.document import TextSplitter, TextSegment

    seg = TextSegment(
        text="| 列A | 列B |\n| --- | --- |\n| 1 | 2 |\n| 3 | 4 |\n| 5 | 6 |",
        kind="table", is_atomic=True,
    )
    splitter = TextSplitter(chunk_size=100, chunk_overlap=0)
    assert len(seg.text) <= splitter.atomic_max_chars, "用例前提：文本须在上界内"
    chunks = splitter.split_segments([seg])
    assert len(chunks) == 1
    assert chunks[0].is_atomic
    assert chunks[0].kind == "table"
    assert chunks[0].text == seg.text


def test_oversized_atomic_is_downgraded():
    """超上界的原子块必须降级切分——否则超出部分被嵌入模型静默截断"""
    from app.utils.document import TextSplitter, TextSegment

    seg = TextSegment(
        text="| 列A | 列B |\n| --- | --- |\n| 1 | 2 |\n| 3 | 4 |\n| 5 | 6 |",
        kind="table", is_atomic=True,
    )
    splitter = TextSplitter(chunk_size=10, chunk_overlap=0)
    chunks = splitter.split_segments([seg])
    assert len(chunks) > 1
    assert all(len(c.text) <= splitter.atomic_max_chars for c in chunks)


def test_atomic_segment_isolated_in_groups():
    """原子段在结构组里独占一组，不与相邻段落合并"""
    from app.utils.document import TextSplitter, TextSegment

    segs = [
        TextSegment(text="前文段落一", kind="paragraph"),
        TextSegment(text="| a | b |\n| --- | --- |\n| 1 | 2 |", kind="table", is_atomic=True),
        TextSegment(text="后文段落二", kind="paragraph"),
    ]
    groups = TextSplitter()._structural_groups(segs)
    # 三段应分成三组：表格独占一组，前后段落各自一组（段落可合并，但本例各 6 字 < 半填充）
    kinds = [[s.kind for s in g] for g in groups]
    assert ["table"] in kinds
