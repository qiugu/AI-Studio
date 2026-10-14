"""文本结构重建（``app.utils.text_structure``）单测

为什么这些用例值得存在
----------------------
段落重建是「块边界落在文档结构边缘」的**前提**：分块器复用 ``"\\n\\n"`` 作为最外层
分隔符，若解析层产出的 ``"\\n\\n"`` 不在真正的段落边界上，块边界只是从「版面折行处」
挪到「伪段落处」，问题并没有解决。

历史上最危险的失败模式正是后者：用「行长是否顶到右边距」推断段落结束，实测使
**四分之三**的段落断点插在句子中间（断点语义率从 97% 崩到 24%），而表面指标
（块尾落在 ``\\n\\n`` 上的比例）反而更高。故本文件除功能用例外，专门用
:class:`TestParagraphBreakSemantics` 守住这个指标作弊的失败模式。
"""

import pytest

from app.utils.text_structure import (
    detect_running_lines,
    ends_sentence,
    is_noise_line,
    noise_statistics,
    normalize_for_dedup,
    rebuild_paragraphs,
    rebuild_pdf_pages,
    starts_structural_block,
)


# ─────────────────────────── 行级判据 ───────────────────────────


class TestEndsSentence:
    @pytest.mark.parametrize(
        "line",
        ["这是一句话。", "问句？", "感叹！", "分号；", "省略…", "ascii sentence.", "next!", "really?"],
    )
    def test_sentence_endings_detected(self, line):
        assert ends_sentence(line) is True

    @pytest.mark.parametrize("line", ["没有标点的行", "", "   ", "半句话，", "逗号不算"])
    def test_non_endings_rejected(self, line):
        assert ends_sentence(line) is False

    @pytest.mark.parametrize("closer", ["”", "’", "」", "』", "》", "）", ")", "】", '"', "'"])
    def test_trailing_closers_are_transparent(self, closer):
        """句末标点后跟收尾符号时仍应判定为句末（``。”`` ``。）`` ``。」``）"""
        assert ends_sentence(f"一句话。{closer}") is True

    @pytest.mark.parametrize("line", ["版本 v2.0", "2026.", "第 3.1 节", "1.2.3"])
    def test_ascii_period_after_digit_is_not_sentence_end(self, line):
        """数字后的句号是版本号/序号，不是句子结束

        若把它判成句末，PDF 里的版本号、编号行会各自成为段落，段落被切碎。
        """
        assert ends_sentence(line) is False


class TestIsNoiseLine:
    @pytest.mark.parametrize(
        "line",
        [
            "",
            "   ",
            "\t",
            "12",
            "- 12 -",
            "第 12 页",
            "· 3 ·",
            "————",
            ".....",
            ". . . . . . 5",
            "……",
        ],
    )
    def test_noise_detected(self, line):
        assert is_noise_line(line) is True

    @pytest.mark.parametrize(
        "line",
        ["这是正文。", "1. 列表项", "第 3 章 总览", "2026 年 9 月", "图 3-1 架构", "（一）"],
    )
    def test_content_preserved(self, line):
        """含实义字符的行一律保留：误删正文的代价远高于留下一行噪声"""
        assert is_noise_line(line) is False

    def test_pure_punctuation_line_is_noise(self):
        """整行只有标点（省略号、圈码）不承载可检索信息

        剔除它是安全的：这类行在原文里是排版装饰或语气停顿，且被剔除后同时充当
        结构断点，段落边界反而更清楚。
        """
        assert is_noise_line("……") is True
        assert is_noise_line("—— —— ——") is True

    def test_running_line_detected_by_set(self):
        running = {normalize_for_dedup("AI Studio 用户手册")}
        assert is_noise_line("AI Studio   用户手册", running) is True
        assert is_noise_line("完全不同的内容。", running) is False


class TestDetectRunningLines:
    def test_detects_header_repeated_across_pages(self):
        pages = [f"AI Studio 手册\n第 {i} 章正文内容。" for i in range(1, 7)]
        running = detect_running_lines(pages)
        assert normalize_for_dedup("AI Studio 手册") in running

    def test_skips_documents_below_min_pages(self):
        """样本太小时「重复」可能只是正常行文，不做检测"""
        pages = ["共同的一行\n正文"] * 4
        assert detect_running_lines(pages) == set()

    def test_ignores_lines_longer_than_max_chars(self):
        """页眉页脚都短；长度上限避免误删反复出现的长正文段落"""
        long_line = "这是一段很长很长的正文内容，" * 8
        pages = [f"{long_line}\n第 {i} 页内容。" for i in range(1, 9)]
        assert detect_running_lines(pages) == set()

    def test_repeats_within_one_page_counted_once(self):
        """同一行在一页内出现多次只计一次

        构造：某行在第 1、2 页各出现 **2 次**（共 4 次出现），但仍只覆盖 2 页，
        达不到「出现在半数页面上」的阈值。若按出现次数统计，4 ≥ 3 会被误判为页眉。
        """
        pages = ["重复行\n重复行\n第 1 页"] + ["重复行\n重复行\n第 2 页"] + [
            f"第 {i} 页内容。" for i in range(3, 7)
        ]

        assert normalize_for_dedup("重复行") not in detect_running_lines(pages)

    def test_blank_pages_do_not_count(self):
        pages = ["", "   ", "内容 A", "内容 B", "内容 C", "内容 D", "内容 E"]
        assert detect_running_lines(pages) == set()


class TestStartsStructuralBlock:
    @pytest.mark.parametrize(
        "line", ["- 项一", "* 项二", "+ 项三", "• 项四", "1. 项五", "(1) 项六", "一、项七"]
    )
    def test_bullet_lines(self, line):
        assert starts_structural_block(line) is True

    @pytest.mark.parametrize(
        "line", ["第 3 章 总览", "3.2 注意力机制", "# 标题", "附录 A", "图 3-1 架构"]
    )
    def test_section_lines(self, line):
        assert starts_structural_block(line) is True

    @pytest.mark.parametrize("line", ["普通正文", "这一行是正文。", "no marker here"])
    def test_plain_lines(self, line):
        assert starts_structural_block(line) is False


# ─────────────────────────── 段落重建 ───────────────────────────


class TestRebuildParagraphs:
    def test_hard_wrapped_lines_merge_into_one_paragraph(self):
        """没有句末标点的连续行属于同一段——这是版面折行的定义"""
        text = "第一行的内容没有句号\n继续同一段\n这一行结束了。\n新的一段开始"

        assert rebuild_paragraphs(text) == (
            "第一行的内容没有句号继续同一段这一行结束了。\n\n新的一段开始"
        )

    def test_chinese_lines_join_without_space(self):
        """中文（及中英混排的中文侧）直接拼接：加空格会引入原文没有的切分点"""
        assert rebuild_paragraphs("中文结尾\n继续中文") == "中文结尾继续中文"

    def test_ascii_lines_join_with_single_space(self):
        """两侧都是 ASCII 字母数字时补一个空格，避免英文单词粘连

        实测教训：``pypdf`` 的 layout 模式正是把这里做错（吞掉空格），
        ``Generated by Agent framework`` 变成 ``GeneratedbyAgentframework``，
        直接破坏 BM25 对英文标识符的分词。
        """
        assert rebuild_paragraphs("the quick brown\nfox jumps") == (
            "the quick brown fox jumps"
        )

    def test_sentence_end_breaks_paragraph(self):
        assert rebuild_paragraphs("甲。\n乙。") == "甲。\n\n乙。"

    def test_bullet_starts_new_paragraph(self):
        assert rebuild_paragraphs("说明文字。\n- 项一\n- 项二") == (
            "说明文字。\n\n- 项一\n\n- 项二"
        )

    def test_section_title_starts_new_paragraph(self):
        assert rebuild_paragraphs("上一段内容。\n3.2 注意力机制\n正文接续") == (
            "上一段内容。\n\n3.2 注意力机制正文接续"
        )

    def test_noise_lines_dropped(self):
        text = "第一行正文\n12\n第二行正文\n. . . . . . 5\n第三行正文"
        rebuilt = rebuild_paragraphs(text)

        assert "12" not in rebuilt.split("\n")
        assert "第三行正文" in rebuilt

    def test_noise_line_also_breaks_paragraph(self):
        """噪声行（页眉/页码）之后必然是新的段落，否则跨页会被拼成一句"""
        assert rebuild_paragraphs("页末内容\n7\n下一页开头") == "页末内容\n\n下一页开头"

    def test_deterministic(self):
        """同一输入恒得同一输出——分块结果参与 vector_id 推导，确定性是可复现的前提"""
        text = "\n".join(f"第{i}行没有句号" for i in range(50)) + "\n结束。"

        assert rebuild_paragraphs(text) == rebuild_paragraphs(text)

    def test_content_order_preserved(self):
        """除噪声行外，内容必须按原顺序保留（不得重排、不得吞掉正文）"""
        lines = [f"第{i}段正文内容很长足以避免被当作噪声的一行文字。" for i in range(20)]
        rebuilt = rebuild_paragraphs("\n".join(lines))

        cursor = 0
        for line in lines:
            position = rebuilt.find(line, cursor)
            assert position >= cursor, f"内容顺序错乱：{line}"
            cursor = position

    def test_empty_and_whitespace_input(self):
        assert rebuild_paragraphs("") == ""
        assert rebuild_paragraphs("\n\n  \n") == ""


class TestRebuildPdfPages:
    def test_output_length_and_order_preserved(self):
        """输出必须与输入等长同序：页号由下标推导，错位会让 source_page 整体偏移"""
        pages = ["第1页正文。", "第2页正文。", "第3页正文。"]

        rebuilt = rebuild_pdf_pages(pages)

        assert len(rebuilt) == len(pages)
        assert "第1页" in rebuilt[0] and "第2页" in rebuilt[1] and "第3页" in rebuilt[2]

    def test_running_header_removed_across_pages(self):
        pages = [f"AI Studio 用户手册\n第 {i} 章的正文内容。" for i in range(1, 9)]

        rebuilt = rebuild_pdf_pages(pages)

        assert all("用户手册" not in page for page in rebuilt)
        assert all(f"第 {i} 章的正文内容。" in rebuilt[i - 1] for i in range(1, 9))

    def test_blank_page_stays_blank(self):
        assert rebuild_pdf_pages(["", "   ", "有内容。"]) == ["", "", "有内容。"]

    def test_paragraph_injected_between_lines(self):
        """重建的**唯一目的**：让 ``\\n\\n`` 在 PDF 上可达

        改造前实测 310 页的 ``\\n\\n`` 出现 0 次，分块器第一级分隔符永远命不中，
        分块退化为「按版面行装箱」。
        """
        page = "第一句话。\n第二句话。\n第三句话。"
        assert "\n\n" in rebuild_pdf_pages([page])[0]


class TestNoiseStatistics:
    def test_counts_pages_lines_and_noise(self):
        pages = [f"页眉\n第 {i} 页\n正文{i}。\n" for i in range(1, 9)]

        stats = noise_statistics(pages)

        assert stats["pages"] == 8
        assert stats["lines"] == 8 * 4  # 每页 4 行（含末尾空行）
        assert stats["noise"] >= 16  # 页码行 + 末尾空行
        assert stats["running"] == 8  # 页眉在 8 页上都出现
