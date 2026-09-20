"""``app.utils.structure_blocks`` 的单元测试

全部用**合成数据**：本模块的判定逻辑是纯函数，不需要真实 PDF 即可覆盖边界。
真实 PDF 上的准确率另有抽样报告（S2 交付），不在单测里断言。

构造要点：``pages`` 与 ``fragments`` 必须**对齐**——``match_signals`` 是按
「去空白后文本相等」配对的，故测试里的片段文本应与页面行文本一致。
"""
from __future__ import annotations

import pytest

from app.utils import structure_blocks as sb
from app.utils.document import HEADING_SEPARATOR as DOC_SEPARATOR


def frag(page=1, y=700.0, text="x", size=10.0, x=0.0, font="PingFangSC-Regular"):
    """构造一个片段（bold/mono 由字体名推导，与实现同源）"""
    return sb.Fragment(
        page=page, text=text, size=size, font=font, x=x, y=y,
        bold=sb.is_bold_font(font), mono=sb.is_mono_font(font),
    )


def doc_lines(*specs):
    """``(page, text, size)`` → DocLine 序列（带信号）"""
    return [
        sb.DocLine(page=p, text=t, signal=sb.LayoutLine(
            page=p, text=t, size=s, x0=0.0, x1=100.0, y=0.0,
            bold=False, mono_share=0.0,
        ))
        for p, t, s in specs
    ]


# ────────────────────────── 契约一致性 ──────────────────────────

def test_heading_separator_matches_document_module():
    """层级分隔符必须与 document 模块完全一致，否则 PDF 与 MD/DOCX 的
    heading_path 无法互相比较（P4 的 section_scope_share 按它计深度）"""
    assert sb.HEADING_SEPARATOR == DOC_SEPARATOR


def test_heading_body_separator_is_single_newline():
    """标题与正文之间必须是单换行：用空行会让分块器在标题后落刀，切出孤儿标题块"""
    assert sb.HEADING_BODY_SEP == "\n"
    assert sb.SECTION_BODY_SEP == "\n\n"


# ────────────────────────── collect_fragment ──────────────────────────

def test_font_size_is_one_and_real_size_comes_from_tm():
    """visitor 的 font_size 恒为 1.0，真实字号由 tm 的缩放还原"""
    f = sb.collect_fragment("标题", None, [18.0, 0.0, 0.0, 18.0, 72.0, 700.0], None, 1.0, 1)
    assert f is not None
    assert f.size == pytest.approx(18.0)
    assert (f.x, f.y) == (72.0, 700.0)


def test_tm_rotation_uses_hypot():
    """tm 含旋转时缩放取 hypot(a, b)，不是单取 a"""
    f = sb.collect_fragment("x", None, [3.0, 4.0, -4.0, 3.0, 0.0, 0.0], None, 2.0, 1)
    assert f is not None
    assert f.size == pytest.approx(10.0)  # hypot(3,4)=5, ×2.0


def test_blank_text_yields_none():
    assert sb.collect_fragment("   ", None, None, None, 12.0, 1) is None
    assert sb.collect_fragment(None, None, None, None, 12.0, 1) is None


def test_missing_tm_falls_back_to_unit_scale():
    """tm 缺失时不得抛异常——真实 PDF 的空白页会出现这种参数"""
    f = sb.collect_fragment("x", None, None, None, 1.0, 1)
    assert f is not None and f.size == pytest.approx(1.0)


def test_font_flags_from_basefont_name():
    assert sb.is_bold_font("/AAAAAB+PingFangSC-Semibold")
    assert sb.is_bold_font("/AAAAAE+OpenSans-Bold")
    assert not sb.is_bold_font("/AAAAAD+PingFangSC-Regular")
    assert sb.is_mono_font("/AAAAAF+Courier")
    assert sb.is_mono_font("/X+Consolas")
    assert not sb.is_mono_font("/AAAAAE+OpenSans-Regular")


# ────────────────────────── fragments_to_lines ──────────────────────────

def test_same_y_fragments_merge_left_to_right():
    """同一行内按 x 排序拼接（用汉字，避免触发 ASCII 补空格规则）"""
    lines = sb.fragments_to_lines([frag(y=700, x=100, text="乙"), frag(y=700, x=10, text="甲")])
    assert len(lines) == 1
    assert lines[0].text == "甲乙"


def test_line_text_join_adds_space_between_ascii_words():
    """英文词间必须补空格，否则破坏 BM25 分词（旧方案否决 layout 模式正因此）"""
    lines = sb.fragments_to_lines([frag(y=700, x=0, text="hello"), frag(y=700, x=50, text="world")])
    assert lines[0].text == "hello world"


def test_line_text_join_no_space_for_cjk():
    lines = sb.fragments_to_lines([frag(y=700, x=0, text="检索"), frag(y=700, x=30, text="增强")])
    assert lines[0].text == "检索增强"


def test_different_y_are_different_lines_and_ordered_top_down():
    """PDF 的 y 轴向上：y 大者在上，阅读顺序须由上而下"""
    lines = sb.fragments_to_lines([frag(y=600, text="low"), frag(y=700, text="high")])
    assert [l.text for l in lines] == ["high", "low"]


def test_pages_are_not_mixed():
    lines = sb.fragments_to_lines([frag(page=2, y=800, text="p2"), frag(page=1, y=700, text="p1")])
    assert [(l.page, l.text) for l in lines] == [(1, "p1"), (2, "p2")]


def test_y_tolerance_scales_with_font_size():
    """容差按字号比例：同样 6 磅的基线偏差，小字号应断开、大字号应合并"""
    small = sb.fragments_to_lines([
        frag(y=700, size=9.0, text="a"), frag(y=706, size=9.0, text="b"),
    ])
    assert len(small) == 2  # 容差 4.5 < 6

    big = sb.fragments_to_lines([
        frag(y=700, size=40.0, text="A"), frag(y=706, size=40.0, text="B"),
    ])
    assert len(big) == 1  # 容差 20 > 6


def test_line_carries_max_size_and_bold_aggregation():
    lines = sb.fragments_to_lines([
        frag(y=700, x=0, size=10.0, text="正文"),
        frag(y=700, x=40, size=18.0, font="X-Bold", text="标题"),
    ])
    assert lines[0].size == pytest.approx(18.0)
    assert lines[0].bold is True
    assert lines[0].x0 == 0.0 and lines[0].x1 == 40.0


def test_empty_fragments_yield_no_lines():
    assert sb.fragments_to_lines([]) == []


# ────────────────────────── match_signals ──────────────────────────

def test_match_by_normalized_text():
    """空白差异不影响配对（归一化去空白）"""
    pages = ["第 1 章  入门"]
    sigs = [frag(y=700, size=17.0, text="第1章 入门")]
    out = sb.match_signals(pages, sigs)
    assert out[0].signal is not None and out[0].signal.size == pytest.approx(17.0)


def test_unmatched_line_has_no_signal():
    """含图页的图题注在 visitor 通道里不存在 ⇒ 无信号，按普通段落处理"""
    pages = ["图1-1 闭环交互"]
    out = sb.match_signals(pages, [])
    assert out[0].signal is None


def test_duplicate_text_consumes_signals_in_order():
    """同一页出现两个相同文本时，按队列顺序消费信号，不重复用同一段信号"""
    pages = ["同名\n同名"]
    sigs = [frag(y=700, text="同名", size=20.0), frag(y=600, text="同名", size=10.0)]
    out = sb.match_signals(pages, sigs)
    assert out[0].signal is not None and out[0].signal.size == pytest.approx(20.0)
    assert out[1].signal is not None and out[1].signal.size == pytest.approx(10.0)


def test_signals_do_not_leak_across_pages():
    pages = ["第一页", "第一页"]
    out = sb.match_signals(pages, [frag(page=1, y=700, text="第一页", size=20.0)])
    assert out[0].signal is not None
    assert out[1].signal is None


def test_empty_lines_are_skipped():
    out = sb.match_signals(["a\n\n   \nb"], [])
    assert [d.text for d in out] == ["a", "b"]


# ────────────────────────── estimate_stats ──────────────────────────

def test_body_size_is_char_weighted_mode():
    """正文主字号按字符数加权：长正文行压过短标题"""
    lines = doc_lines((1, "正" * 200, 10.0), (1, "标题", 24.0))
    stats = sb.estimate_stats(lines, [])
    assert stats.body_size == pytest.approx(10.0)


def test_body_size_ignores_lines_without_signal():
    lines = [sb.DocLine(page=1, text="x" * 500, signal=None)]
    stats = sb.estimate_stats(lines, [])
    assert stats.body_size == pytest.approx(10.0)  # 兜底值


def test_mono_usable_disabled_when_document_is_mostly_mono():
    """PPT 导出文档等宽占 60% ⇒「等宽＝代码」必须整篇禁用"""
    frags = [frag(font="X-Courier") for _ in range(6)] + [frag(font="X-Regular") for _ in range(4)]
    stats = sb.estimate_stats([], frags)
    assert stats.mono_share == pytest.approx(0.6)
    assert stats.mono_usable is False


def test_mono_usable_when_share_is_low():
    frags = [frag(font="X-Courier")] + [frag(font="X-Regular") for _ in range(19)]
    assert sb.estimate_stats([], frags).mono_usable is True


# ────────────────────────── level_for_size ──────────────────────────

@pytest.mark.parametrize("ratio,expected", [
    (3.70, 1), (2.00, 1), (1.99, 2), (1.50, 2), (1.49, 3),
    (1.30, 3), (1.29, 4), (1.20, 4), (1.19, 5), (1.12, 5), (1.11, 6),
])
def test_level_tiers(ratio, expected):
    assert sb.level_for_size(10.0 * ratio, 10.0) == expected


def test_level_never_exceeds_six():
    """层级上限与 Markdown 的 ###### 对齐，避免出现 H7：比正文还小者落到最深档"""
    assert sb.level_for_size(10.0 * 0.9, 10.0) == sb.MAX_HEADING_LEVEL
    assert sb.MAX_HEADING_LEVEL == 6


# ────────────────────────── 行分类 ──────────────────────────

def make_stats(body=10.0, mono_share=0.0):
    return sb.DocStats(body_size=body, mono_share=mono_share)


def test_no_signal_is_paragraph_never_heading():
    """无信号 ⇒ 无判据 ⇒ 必须回落为普通段落（本模块的保守原则）"""
    verdict = sb.classify_line(sb.DocLine(page=1, text="短标题"), make_stats())
    assert verdict.kind == "paragraph"
    assert verdict.score == 0.0


def test_large_font_becomes_heading():
    line = sb.DocLine(page=1, text="第 1 章 入门", signal=sb.LayoutLine(
        page=1, text="第 1 章 入门", size=17.0, x0=0, x1=100, y=0, bold=False, mono_share=0.0))
    verdict = sb.classify_line(line, make_stats(body=10.0))
    assert verdict.is_heading
    assert verdict.level == 2


def test_body_size_text_stays_paragraph():
    line = sb.DocLine(page=1, text="这是一段很长的正文，讲述如何构建检索增强生成系统，需要处理切分、嵌入、召回与重排等多个环节。",
                      signal=sb.LayoutLine(page=1, text="x", size=10.0, x0=0, x1=100, y=0,
                                           bold=False, mono_share=0.0))
    assert sb.classify_line(line, make_stats()).kind == "paragraph"


def test_caption_is_not_heading_even_at_heading_size():
    """图/表题注的字号常与标题相同，必须单独摘出，否则污染 heading_path"""
    verdict = sb.classify_line(sb.DocLine(page=1, text="图1-1 Agent 与环境的闭环", signal=None),
                               make_stats())
    assert verdict.kind == "caption"


@pytest.mark.parametrize("text", ["图2.3 循环神经网络", "表 3-1 参数表", "Figure 2.1 Architecture", "Table 3"])
def test_caption_patterns(text):
    assert sb.is_caption_line(text)


@pytest.mark.parametrize("text", ["图书管理", "表情包", "图表工具"])
def test_caption_requires_digits(text):
    """仅以「图/表」开头但后无编号者不是题注（避免误杀正常词汇）"""
    assert not sb.is_caption_line(text)


def test_toc_page_lines_are_marked_not_headings():
    line = sb.DocLine(page=1, text="第 7 章 工具 23", signal=sb.LayoutLine(
        page=1, text="x", size=17.0, x0=0, x1=100, y=0, bold=False, mono_share=0.0))
    assert sb.classify_line(line, make_stats(), toc_page=True).kind == "toc"


def test_code_detected_via_mono_signal():
    """行级等宽纯度足够 ⇒ 判为代码（与文档级基率无关）"""
    line = sb.DocLine(page=1, text="x = 1", signal=sb.LayoutLine(
        page=1, text="x = 1", size=10.0, x0=0, x1=100, y=0, bold=False, mono_share=0.9))
    assert sb.classify_line(line, make_stats(mono_share=0.05)).kind == "code"


def test_mono_heavy_document_raises_bar_instead_of_disabling():
    """文档级等宽基率高时，**抬高单行门槛**而非整篇禁用判据

    旧行为（按整篇基率否决）会把「代码多」误判成「等宽不可信」——实测
    ``Happy-LLM`` 的 code 块因此从 475 个归零。
    """
    # 行级纯度 0.9 ≥ 归一后的门槛 0.85 ⇒ 仍判代码
    strong = sb.DocLine(page=1, text="x = 1", signal=sb.LayoutLine(
        page=1, text="x = 1", size=10.0, x0=0, x1=100, y=0, bold=False, mono_share=0.9))
    assert sb.classify_line(strong, make_stats(mono_share=0.9)).kind == "code"
    # 纯度不足（0.5）且无词法特征 ⇒ 不判代码
    weak = sb.DocLine(page=1, text="这是一行普通的正文内容", signal=sb.LayoutLine(
        page=1, text="x", size=10.0, x0=0, x1=100, y=0, bold=False, mono_share=0.5))
    assert sb.classify_line(weak, make_stats(mono_share=0.9)).kind != "code"


def test_heading_score_combines_signals():
    """字号(1.44→2.5) + 编号(0.5) + 短行(0.5) = 3.5，过阈值"""
    line = sb.DocLine(page=1, text="1.1 现代 Agent", signal=sb.LayoutLine(
        page=1, text="x", size=14.4, x0=0, x1=100, y=0, bold=False, mono_share=0.0))
    assert sb.classify_line(line, make_stats(body=10.0)).is_heading


def test_marginal_size_alone_is_not_enough():
    """仅字号略大（1.05）不足以判标题——避免把正文里的强调行写成出处"""
    line = sb.DocLine(page=1, text="这是一句普通的正文内容，长度也超过了短行阈值，不应被当成标题处理。",
                      signal=sb.LayoutLine(page=1, text="x", size=10.5, x0=0, x1=100, y=0,
                                           bold=False, mono_share=0.0))
    assert not sb.classify_line(line, make_stats(body=10.0)).is_heading


@pytest.mark.parametrize("text,expected", [
    ("第 3 章 工具", True), ("附录 A 术语表", True), ("3.2 检索", True),
    ("3.2.1 重排", True), ("工具", False), ("2026", False),
])
def test_numbered_heading(text, expected):
    assert sb.is_numbered_heading(text) is expected


def test_numbered_heading_is_not_list_item():
    assert not sb.is_list_item_line("3.2 检索")
    assert sb.is_list_item_line("- 检索")
    assert sb.is_list_item_line("1. 检索")


# ────────────────────────── 目录页判定 ──────────────────────────

def test_toc_page_by_dot_leaders():
    lines = [sb.DocLine(page=1, text=f"第 {i} 章 标题 .......... {i}") for i in range(1, 9)]
    assert sb.is_toc_page(lines)


def test_toc_page_by_numbered_entries_with_page_numbers():
    lines = [sb.DocLine(page=1, text=f"第 {i} 章 工具 {20 + i}") for i in range(1, 9)]
    assert sb.is_toc_page(lines)


def test_normal_page_is_not_toc():
    lines = [sb.DocLine(page=1, text="这是一段正文，不含任何目录特征。") for _ in range(10)]
    assert not sb.is_toc_page(lines)


def test_toc_needs_minimum_entries():
    """只有一两条像目录的行时不能整页判为目录，否则会误伤正文"""
    lines = [sb.DocLine(page=1, text="第 1 章 工具 23")]
    assert not sb.is_toc_page(lines)


# ────────────────────────── build_blocks ──────────────────────────

def test_build_blocks_assigns_heading_path():
    """正文必须**足够长**，否则按字符数加权的「正文主字号」会被标题抢走"""
    body = "正文内容。" * 10
    pages = [f"第 1 章 入门\n{body}"]
    frags = [frag(y=700, size=17.0, text="第 1 章 入门"), frag(y=680, size=10.0, text=body)]
    blocks = sb.build_blocks(pages, frags)
    assert [b.kind for b in blocks] == ["heading", "paragraph"]
    assert blocks[0].heading_path == "第 1 章 入门"
    assert blocks[1].heading_path == "第 1 章 入门"
    assert blocks[0].level == 2


def test_heading_path_nests_and_pops():
    """层级栈：同级或更浅的新标题必须把旧的弹出，否则路径会串

    正文行刻意写长（每段 20 字）——短文档里按字符加权的众数会平票，
    不足以代表真实排版；这里要测的是栈行为，不是估计器。
    """
    body_a = "正文甲" * 10 + "。"
    body_b = "正文乙" * 10 + "。"
    pages = [f"第 1 章\n3.1 甲\n{body_a}\n第 2 章\n{body_b}"]
    frags = [
        frag(y=700, size=30.0, text="第 1 章"),
        frag(y=680, size=15.0, text="3.1 甲"),
        frag(y=660, size=10.0, text=body_a),
        frag(y=640, size=30.0, text="第 2 章"),
        frag(y=620, size=10.0, text=body_b),
    ]
    blocks = sb.build_blocks(pages, frags)
    paths = {b.text: b.heading_path for b in blocks}
    assert paths["3.1 甲"] == "第 1 章 > 3.1 甲"
    assert paths[body_a] == "第 1 章 > 3.1 甲"
    assert paths[body_b] == "第 2 章"


def test_heading_stack_survives_page_boundary():
    """一章跨多页，路径必须延续——否则第 2 页的正文会失去出处"""
    pages = ["第 1 章\n第一页正文。", "第二页正文。"]
    frags = [
        frag(page=1, y=700, size=30.0, text="第 1 章"),
        frag(page=1, y=680, size=10.0, text="第一页正文。"),
        frag(page=2, y=700, size=10.0, text="第二页正文。"),
    ]
    blocks = sb.build_blocks(pages, frags)
    assert all(b.heading_path == "第 1 章" for b in blocks if b.kind != "heading")
    assert blocks[-1].page == 2


def test_blocks_are_single_page():
    pages = ["甲。", "乙。"]
    frags = [frag(page=1, y=700, text="甲。"), frag(page=2, y=700, text="乙。")]
    blocks = sb.build_blocks(pages, frags)
    assert all(b.page == b.page_end for b in blocks)


def test_wrapped_lines_fold_into_one_paragraph():
    """折行续写必须合并（上行未结句）"""
    pages = ["上一行没有句末标点\n续写部分。"]
    frags = [frag(y=700, text="上一行没有句末标点"), frag(y=680, text="续写部分。")]
    blocks = sb.build_blocks(pages, frags)
    assert len(blocks) == 1
    assert blocks[0].text == "上一行没有句末标点续写部分。"


def test_sentence_end_breaks_paragraph():
    pages = ["第一句。\n第二句。"]
    frags = [frag(y=700, text="第一句。"), frag(y=680, text="第二句。")]
    blocks = sb.build_blocks(pages, frags)
    assert [b.text for b in blocks] == ["第一句。", "第二句。"]


def test_noise_lines_are_dropped():
    pages = ["正文。\n12\n更多正文。"]
    frags = [frag(y=700, text="正文。"), frag(y=680, text="12"), frag(y=660, text="更多正文。")]
    blocks = sb.build_blocks(pages, frags)
    assert all("12" != b.text for b in blocks)


def test_toc_entries_grouped_as_toc_not_heading():
    toc = [f"第 {i} 章 标题 .......... {i}" for i in range(1, 9)]
    pages = ["\n".join(toc)]
    blocks = sb.build_blocks(pages, [])
    assert blocks
    assert all(b.kind == "toc" for b in blocks)


def test_build_blocks_empty_input():
    assert sb.build_blocks([], []) == []


# ────────────────────────── to_sections ──────────────────────────

def test_section_keeps_heading_with_body():
    """标题必须与其正文同节——否则分块器会在标题与正文之间落刀，切出孤儿标题块"""
    blocks = [
        sb.Block(kind="heading", text="第 1 章", page=1, page_end=1, level=2, heading_path="第 1 章"),
        sb.Block(kind="paragraph", text="正文。", page=1, page_end=1, heading_path="第 1 章"),
    ]
    sections = sb.to_sections(blocks)
    assert len(sections) == 1
    assert sections[0].text == "第 1 章\n正文。"
    assert sections[0].heading_path == "第 1 章"


def test_section_joins_two_paragraphs_with_blank_line():
    blocks = [
        sb.Block(kind="heading", text="H", page=1, page_end=1, level=2, heading_path="H"),
        sb.Block(kind="paragraph", text="甲。", page=1, page_end=1, heading_path="H"),
        sb.Block(kind="paragraph", text="乙。", page=1, page_end=1, heading_path="H"),
    ]
    sections = sb.to_sections(blocks)
    assert sections[0].text == "H\n甲。\n\n乙。"


def test_heading_without_body_is_its_own_section():
    blocks = [sb.Block(kind="heading", text="H", page=1, page_end=1, level=2, heading_path="H")]
    sections = sb.to_sections(blocks)
    assert len(sections) == 1 and sections[0].text == "H"


def test_consecutive_headings_each_start_a_section():
    blocks = [
        sb.Block(kind="heading", text="H1", page=1, page_end=1, level=1, heading_path="H1"),
        sb.Block(kind="heading", text="H2", page=1, page_end=1, level=2, heading_path="H1 > H2"),
    ]
    sections = sb.to_sections(blocks)
    assert [s.text for s in sections] == ["H1", "H2"]
    assert [s.heading_path for s in sections] == ["H1", "H1 > H2"]


def test_table_is_standalone_section():
    blocks = [
        sb.Block(kind="paragraph", text="前文。", page=1, page_end=1, heading_path="H"),
        sb.Block(kind="table", text="| a | b |", page=1, page_end=1, heading_path="H"),
        sb.Block(kind="paragraph", text="后文。", page=1, page_end=1, heading_path="H"),
    ]
    sections = sb.to_sections(blocks)
    assert len(sections) == 3
    assert sections[1].text == "| a | b |"


def test_page_break_is_hard_boundary():
    """节不跨页：截断发生在页边界而非段落中间，故 section.page 恒为精确单页。

    这样出处页码无需扩展 TextSegment / 分块器的 _segment_bounds 契约即可保持精确。
    """
    blocks = [
        sb.Block(kind="heading", text="H", page=3, page_end=3, level=2, heading_path="H"),
        sb.Block(kind="paragraph", text="正文。", page=4, page_end=4, heading_path="H"),
    ]
    sections = sb.to_sections(blocks)
    assert len(sections) == 2
    assert [(s.page, s.page_end) for s in sections] == [(3, 3), (4, 4)]
    assert all(s.heading_path == "H" for s in sections)


def test_sections_of_empty_input():
    assert sb.to_sections([]) == []


# ══════════════════════ 表格质量守卫（P0，见 plan-table-rendering-fix §2） ══════════════════════
#
# 背景：PPT 导出的 PDF 里，装饰性矢量矩形能自证「四边被网格线覆盖」而被判成表格，
# 实测 171 页每页产出 1 张、单元格非空率仅 4.2%、最大 145 列，并连带把整页正文
# 抹成空格（heading_path 覆盖率归零）。以下用例钉死各条守卫。

def _table(n_rows=2, n_cols=2, filled=4, chars=40, page=1):
    return sb.TableBox(
        page=page, bbox=(0.0, 0.0, 600.0, 800.0),
        markdown="| a |\n| --- |\n| 1 |", n_rows=n_rows, n_cols=n_cols,
        filled_cells=filled, text_chars=chars,
    )


def test_table_rejected_when_columns_exceed_limit():
    """列数超限必须否决——伪表格实测达 145 列（bbox 内所有装饰线都成了网格线）"""
    assert sb._table_is_credible(_table(n_cols=sb._MAX_TABLE_COLS + 1)) is False


def test_table_rejected_when_fill_ratio_too_low():
    """填充率过低 ⇒ 装饰线围成的空框，不是表格"""
    assert sb._table_is_credible(_table(n_rows=10, n_cols=10, filled=5)) is False


def test_table_rejected_when_cells_are_fragments():
    """单元格平均字符数 < 2 ⇒ 碎片而非单元格内容"""
    assert sb._table_is_credible(_table(filled=4, chars=4)) is False


def test_table_accepted_when_quality_met():
    assert sb._table_is_credible(_table()) is True


def test_table_default_quality_fields_are_untrusted():
    """未填质量字段的构造点（默认 0）必须视为不可信，而非默认可信"""
    bare = sb.TableBox(page=1, bbox=(0.0, 0.0, 1.0, 1.0), markdown="x", n_rows=2, n_cols=2)
    assert sb._table_is_credible(bare) is False


# ══════════════════════ 线框检测规模上界（P0） ══════════════════════

def _grid_lines(n, span=600.0):
    """构造 n 条横线 + n 条竖线（间隔 10 磅，确保不被 _GRID_TOL 聚类合并）"""
    lines = [sb.GeometryLine(0.0, i * 10.0, span, i * 10.0, 1) for i in range(n)]
    lines += [sb.GeometryLine(i * 10.0, 0.0, i * 10.0, 800.0, 1) for i in range(n)]
    return lines


def test_ruled_detection_bails_out_on_huge_grid():
    """网格线数超上界 ⇒ 放弃该页

    候选矩形数是 O(H²V²)，无上界时第 26 页内存以 ~12 MB/s 无界增长，
    实测把 backend 容器跑成 OOM 重启。本用例把该安全阀钉死。
    """
    assert sb._detect_ruled_tables(1, _grid_lines(sb._MAX_GRID_LINES + 1), []) == []


def test_ruled_detection_still_works_on_small_grid():
    """正常规模的网格线不得被上界误杀"""
    lines = [
        sb.GeometryLine(0.0, 0.0, 600.0, 0.0, 1),
        sb.GeometryLine(0.0, 50.0, 600.0, 50.0, 1),
        sb.GeometryLine(0.0, 100.0, 600.0, 100.0, 1),
        sb.GeometryLine(0.0, 0.0, 0.0, 100.0, 1),
        sb.GeometryLine(300.0, 0.0, 300.0, 100.0, 1),
        sb.GeometryLine(600.0, 0.0, 600.0, 100.0, 1),
    ]
    frags = [
        frag(y=75.0, x=20.0, text="AAA"), frag(y=75.0, x=320.0, text="BBB"),
        frag(y=25.0, x=20.0, text="CCC"), frag(y=25.0, x=320.0, text="DDD"),
    ]
    assert sb._detect_ruled_tables(1, lines, frags), "正常 2×2 线框应能识别为表格"


def test_grid_line_must_span_the_whole_region():
    """只覆盖一部分宽度的线不得参与切分单元格

    旧实现按「坐标落在 bbox 内」过滤，包围盒被并成整页后每条装饰线都成了网格线，
    列数因此等于「该页竖线数 − 1」（实测 145 列）。
    """
    lines = [
        sb.GeometryLine(0.0, 0.0, 600.0, 0.0, 1),
        sb.GeometryLine(0.0, 50.0, 600.0, 50.0, 1),
        sb.GeometryLine(0.0, 100.0, 600.0, 100.0, 1),
        sb.GeometryLine(0.0, 0.0, 0.0, 100.0, 1),
        sb.GeometryLine(300.0, 0.0, 300.0, 100.0, 1),
        sb.GeometryLine(600.0, 0.0, 600.0, 100.0, 1),
        # 一条只覆盖右上角 20 磅的装饰竖线（不跨越区域高度）
        sb.GeometryLine(450.0, 80.0, 450.0, 100.0, 1),
    ]
    frags = [
        frag(y=75.0, x=20.0, text="AAA"), frag(y=75.0, x=320.0, text="BBB"),
        frag(y=25.0, x=20.0, text="CCC"), frag(y=25.0, x=320.0, text="DDD"),
    ]
    out = sb._detect_ruled_tables(1, lines, frags)
    assert out and out[0].n_cols == 2, "短装饰线不应增加列数"


# ══════════════════════ 抹除面积保护（P0） ══════════════════════

def _spread_frags():
    return [frag(x=float(x), y=float(y)) for x in (0.0, 300.0, 600.0) for y in (0.0, 400.0, 800.0)]


def test_covers_page_true_for_layout_background():
    """覆盖整页内容范围的「表格」更可能是版式背景 ⇒ 不应抹除正文"""
    assert sb._covers_page((0.0, 0.0, 600.0, 800.0), _spread_frags()) is True


def test_covers_page_false_for_small_region():
    assert sb._covers_page((0.0, 700.0, 200.0, 800.0), _spread_frags()) is False


def test_covers_page_needs_enough_samples():
    """样本太少时判据不可靠 ⇒ 保守返回 False（宁可放过，不可误杀）"""
    assert sb._covers_page((0.0, 0.0, 600.0, 800.0), [frag()]) is False


def test_blank_text_keeps_body_when_table_covers_page():
    """端到端：整页版式背景不得把正文抹成空格"""
    pages = ["第一段正文。\n第二段正文。"]
    table = sb.TableBox(page=1, bbox=(0.0, 0.0, 600.0, 800.0), markdown="| a |\n| --- |\n| 1 |",
                        n_rows=2, n_cols=2, filled_cells=4, text_chars=40)
    frags = [frag(text="第一段正文。", x=0.0, y=100.0), frag(text="第二段正文。", x=0.0, y=80.0),
             frag(text="x", x=600.0, y=0.0), frag(text="y", x=0.0, y=800.0)]
    cleaned = sb._blank_table_text(pages, [table], frags)
    assert "正文" in cleaned[0], "覆盖整页的表格不应触发抹除"


# ══════════════════════ 无线框表格：排除代码行（P0） ══════════════════════

def test_code_row_excluded_from_borderless_detection():
    """等宽代码的 token 位置逐行对齐，天然满足列对齐判据 ⇒ 必须排除"""
    stats = sb.DocStats(body_size=10.0, mono_share=0.6)
    row = [frag(text=t, font="X-Courier") for t in ("self", ".", "wq", "=", "nn", ".", "Linear")]
    assert sb._row_is_code_like(row, stats) is True


def test_plain_row_not_excluded():
    stats = sb.DocStats(body_size=10.0, mono_share=0.0)
    row = [frag(text="索引"), frag(text="：将文档库分割成较短的片段")]
    assert sb._row_is_code_like(row, stats) is False


def test_borderless_needs_three_rows():
    """无线框路径门槛比线框路径更严（3 行）——2 行是列对齐最易偶然成立的规模"""
    assert sb._MIN_BORDERLESS_ROWS > sb._MIN_TABLE_ROWS


# ══════════════════════ 代码识别：多信号（C1 / C3） ══════════════════════

def _line(text, mono_share=0.0):
    return sb.DocLine(page=1, text=text, signal=sb.LayoutLine(
        page=1, text=text, size=10.0, x0=0.0, x1=100.0, y=0.0,
        bold=False, mono_share=mono_share))


@pytest.mark.parametrize("text", [
    "def attention(q, k, v):",
    "import torch",
    "return scores",
    "self.wq = nn.Linear(dim, dim)",
    "# 输出权重矩阵。",
    "# Softmax",
    "// 初始化权重",
])
def test_code_rows_detected_without_mono(text):
    """多信号判据：**不依赖等宽字体**即可认出代码行（含中文注释）

    这条修复的直接动机：旧实现用「文档级等宽基率」当整篇门禁，实测 Happy-LLM
    等宽占 60.03% 导致代码识别被整篇禁用（code 块 475 → 0）。而分页统计证明
    等宽恰是代码页的特有信号（p1–p7 为 0%、p8 起 22–30%）。
    """
    assert sb.classify_line(_line(text), make_stats(mono_share=0.0)).kind == "code"


@pytest.mark.parametrize("text", [
    "这是一段普通的正文内容，讲述如何构建检索增强生成系统。",
    "参考⽂献",
    "图1-1 Agent 与环境的闭环",
])
def test_plain_rows_not_code(text):
    assert sb.classify_line(_line(text), make_stats(mono_share=0.0)).kind != "code"


def test_chinese_comment_beats_sentence_end_penalty():
    """注释行豁免「句末标点」否证——中文注释同样以「。」收尾"""
    assert sb.looks_like_code("# 输出权重矩阵。", _line("# 输出权重矩阵。").signal, make_stats()) is True


def test_trailing_full_stop_penalises_plain_text():
    """正文行以「。」收尾是**否证**（无代码特征时不得判码）"""
    assert sb.looks_like_code("这是一句普通正文。", _line("这是一句普通正文。").signal, make_stats()) is False


def test_python_comment_is_not_list_item():
    """C3：``# 注释`` 在 list_item 判据里是「结构起点」，必须先被代码判据摘出

    旧实现下 ``# 输出权重矩阵。`` 会被摘成 9 字符的 ``list_item`` 碎片块。
    """
    assert sb.classify_line(_line("# 输出权重矩阵。"), make_stats()).kind != "list_item"
    # 顺序才是关键，而非 is_list_item_line 本身有误——它对 `#` 确实返回 True
    assert sb.is_list_item_line("# 输出权重矩阵。") is True


def test_code_score_shared_by_both_callers():
    """判据只有一份：行分类与表格检测走同一函数，避免两处口径漂移"""
    stats = make_stats(mono_share=0.0)
    assert sb.looks_like_code("import os", _line("import os").signal, stats) is True
    assert sb._code_score("import os", 0.0, stats) >= sb.CODE_MIN_SCORE


# ══════════════════════ code 独立成节（C2） ══════════════════════

def test_code_is_standalone_section():
    """代码必须自成一节：否则 kind 取 parts[0].kind 而退化为 heading/paragraph，
    is_atomic 随之丢失，代码随后被 chunk_size 机械切碎（实测 475 个 Block 只剩 51 节）"""
    blocks = [
        sb.Block(kind="heading", text="H", page=1, page_end=1, level=2, heading_path="H"),
        sb.Block(kind="paragraph", text="前文。", page=1, page_end=1, heading_path="H"),
        sb.Block(kind="code", text="def f():", page=1, page_end=1, heading_path="H"),
    ]
    sections = sb.to_sections(blocks)
    assert [s.kind for s in sections] == ["heading", "code"]
    assert sections[1].text == "def f():"


def test_consecutive_code_blocks_merge_into_one_section():
    """一个函数常被页内分组切成多个 Block，合并后才完整"""
    blocks = [
        sb.Block(kind="code", text="def f():", page=1, page_end=1, heading_path=None),
        sb.Block(kind="code", text="    return 1", page=1, page_end=1, heading_path=None),
    ]
    sections = sb.to_sections(blocks)
    assert len(sections) == 1
    assert sections[0].kind == "code"
    assert "def f():" in sections[0].text and "return 1" in sections[0].text


def test_paragraph_after_code_starts_new_section():
    """正文块紧接代码节 ⇒ 必须先封住代码节，避免混节导致 kind 退化"""
    blocks = [
        sb.Block(kind="code", text="def f():", page=1, page_end=1, heading_path=None),
        sb.Block(kind="paragraph", text="说明文字。", page=1, page_end=1, heading_path=None),
    ]
    sections = sb.to_sections(blocks)
    assert [s.kind for s in sections] == ["code", "paragraph"]
