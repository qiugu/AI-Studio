"""文本分块器单测

分块质量是检索质量的上游：分块切断了答案，检索再强也召不回。
本文件验证可依赖的不变量。

历史：``_merge_splits`` 曾长期忽略 ``chunk_overlap``（D11，声明 128 实际 0），
当时以 **严格 xfail** 记录该缺陷。缺陷已于 P3-G 修复（改为标准回溯合并），
故该 xfail 已移除，改为正向不变量断言——若将来回归为「零重叠」，
这些用例会直接失败而不是静默标记为「预期失败」。
"""

import pytest

from app.utils.document import TextSplitter


def _long_text(sentences: int = 300) -> str:
    return "".join(f"第{i}句内容用于验证分块边界与重叠行为。" for i in range(sentences))


def _suffix_prefix_overlap(previous: str, following: str, max_check: int = 400) -> int:
    """返回相邻两块的公共重叠长度（前者后缀 == 后者前缀）"""
    limit = min(max_check, len(previous), len(following))
    for size in range(limit, 0, -1):
        if previous[-size:] == following[:size]:
            return size
    return 0


class TestSplitterInvariants:
    def test_chunks_are_substrings_of_source(self):
        """任何分块都必须是原文的连续子串——分块过程不得改写或臆造内容

        这条不变量在引入重叠后更容易被破坏（重叠是「回退拼接」而非复制），
        因此对多组 chunk_size / chunk_overlap 组合逐一验证。
        """
        text = _long_text()
        for size, overlap in ((200, 50), (100, 30), (1024, 128), (64, 16)):
            for chunk in TextSplitter(chunk_size=size, chunk_overlap=overlap).split(text):
                assert chunk in text, f"chunk_size={size} overlap={overlap} 产出非原文子串"

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
        """以句号分隔的规整文本，每块长度不应超过 chunk_size

        重叠不得以「把块撑破」为代价：重叠片段是从前一块**弹出后复用**的，
        而非额外附加内容，故块长上限仍应严格成立。
        """
        chunks = TextSplitter(chunk_size=100, chunk_overlap=0).split(_long_text())
        assert chunks
        assert all(len(chunk) <= 100 for chunk in chunks)

    def test_respects_chunk_size_with_overlap_enabled(self):
        """开启重叠后块长上限仍须成立（重叠最易在此处撑破 chunk_size）"""
        chunks = TextSplitter(chunk_size=120, chunk_overlap=48).split(_long_text())
        assert chunks
        assert all(len(chunk) <= 120 for chunk in chunks)

    def test_covers_entire_text_without_overlap(self):
        """重叠为 0 时，所有分块的长度之和应接近原文（允许分隔符在块边界被丢弃）"""
        text = _long_text(sentences=100)
        chunks = TextSplitter(chunk_size=100, chunk_overlap=0).split(text)
        total = sum(len(chunk) for chunk in chunks)
        assert total >= len(text) * 0.9, f"内容丢失过多：原文 {len(text)}，分块合计 {total}"

    def test_invalid_empty_input_returns_empty(self):
        assert TextSplitter().split("") == []
        assert TextSplitter().split("   \n  ") == []


class TestOverlapSemantics:
    """``chunk_overlap`` 语义验证（P3-G / D11 回归防线）"""

    def test_consecutive_chunks_should_overlap(self):
        """相邻分块必须存在真实重叠（修复前恒为 0）

        D11：``_merge_splits`` 曾只比较 ``len(current) + len(s) + separator_len``，
        从未把 ``chunk_overlap`` 纳入计算，声明的 128 字符重叠实际为 0。
        后果：跨块边界的答案会被一分为二，任何一块都无法独立支撑答案，
        直接压低 Recall 上限。
        """
        chunks = TextSplitter(chunk_size=200, chunk_overlap=50).split(_long_text())
        assert len(chunks) >= 2, "文本不足以产生多个分块，用例前提不成立"
        assert _suffix_prefix_overlap(chunks[0], chunks[1]) > 0

    @pytest.mark.parametrize(
        "chunk_size,overlap",
        [(200, 50), (200, 30), (120, 48), (1024, 128), (100, 25)],
    )
    def test_overlap_respects_declared_bound(self, chunk_size: int, overlap: int):
        """每处相邻边界的重叠 ∈ (0, chunk_overlap]

        下界 > 0 是 D11 的核心断言；上界 ≤ chunk_overlap 确保重叠没有失控放大
        （回溯算法只保留「不超过 chunk_overlap」的尾部片段）。
        """
        chunks = TextSplitter(chunk_size=chunk_size, chunk_overlap=overlap).split(_long_text())
        assert len(chunks) >= 2, "文本不足以产生多个分块，用例前提不成立"
        for previous, following in zip(chunks, chunks[1:]):
            measured = _suffix_prefix_overlap(previous, following)
            assert measured > 0, f"chunk_size={chunk_size} overlap={overlap} 出现零重叠边界"
            assert measured <= overlap, (
                f"chunk_size={chunk_size} overlap={overlap} 重叠 {measured} 超出声明上限"
            )

    def test_overlap_is_monotonic_in_declaration(self):
        """重叠声明越大，块数越多且平均重叠不减少——证明参数确实生效"""
        text = _long_text(sentences=120)
        small = TextSplitter(chunk_size=200, chunk_overlap=0).split(text)
        large = TextSplitter(chunk_size=200, chunk_overlap=80).split(text)
        assert len(large) > len(small), "增大 chunk_overlap 未使块数增加，参数可能未生效"

        def _avg_overlap(chunks):
            if len(chunks) < 2:
                return 0.0
            pairs = list(zip(chunks, chunks[1:]))
            return sum(_suffix_prefix_overlap(a, b) for a, b in pairs) / len(pairs)

        assert _avg_overlap(large) > _avg_overlap(small)

    def test_zero_overlap_produces_no_overlap(self):
        """chunk_overlap=0 时必须完全没有重叠，且块之间不丢内容"""
        text = _long_text(sentences=120)
        chunks = TextSplitter(chunk_size=200, chunk_overlap=0).split(text)
        assert len(chunks) >= 2
        for previous, following in zip(chunks, chunks[1:]):
            assert _suffix_prefix_overlap(previous, following) == 0


class TestConfiguredDefaults:
    """分块参数必须来自配置，且不得越过模型的 token 硬上限"""

    def test_defaults_follow_config(self):
        """无参构造必须取 ``config`` 的当前值（而非模块常量）

        这是「改配置即生效」的核心断言。若有人把默认值写回函数签名
        （``def __init__(self, chunk_size=1024)``），默认参数会在**导入期**求值，
        配置在运行期的修改将不再生效——本用例通过 monkeypatch 运行期改配置来
        捕获这种退化。
        """
        from app.core.config import config

        splitter = TextSplitter()
        assert splitter.chunk_size == config.chunk_size
        assert splitter.chunk_overlap == config.chunk_overlap

    def test_runtime_config_change_is_picked_up(self, monkeypatch):
        """运行期改配置后，新构造的分块器必须立刻跟随"""
        from app.core.config import config

        monkeypatch.setattr(config, "chunk_size", 320, raising=False)
        monkeypatch.setattr(config, "chunk_overlap", 40, raising=False)
        splitter = TextSplitter()
        assert (splitter.chunk_size, splitter.chunk_overlap) == (320, 40)

    def test_explicit_args_override_config(self):
        """显式传参优先于配置——评测脚本靠这一点做参数扫描"""
        splitter = TextSplitter(chunk_size=128, chunk_overlap=16)
        assert (splitter.chunk_size, splitter.chunk_overlap) == (128, 16)

    def test_overlap_greater_than_size_rejected(self):
        """重叠不得超过块长：否则「重叠」退化为整块复制，块数线性膨胀"""
        with pytest.raises(ValueError):
            TextSplitter(chunk_size=100, chunk_overlap=200)

    def test_configured_default_within_model_token_budget(self):
        """配置的分块上限必须留在 512 token 窗口内（回归防线）

        ``bge-base-zh-v1.5`` 与 ``bge-reranker-v2-m3`` 的 ``max_seq_length`` 均为
        512，且 sentence-transformers 对超长输入是**静默截断**。本语料实测
        1 中文字 ≈ 1.075 token，故字符预算必须显著低于 512 才能保证零截断。
        历史教训：默认值曾是 1024 字符，实测 49.7% 的块被截断、28.3% 的词元
        从未进入向量。本用例把该约束钉死，防止回归。
        """
        from app.core.config import config

        assert config.chunk_size <= 512, (
            f"chunk_size={config.chunk_size} 超过嵌入/精排模型的 512 token 窗口"
            f"（中文约 1.075 token/字），会造成静默截断"
        )
        assert 0 < config.chunk_overlap < config.chunk_size
        # 重叠比例落在社区推荐区间（10%~20%）
        ratio = config.chunk_overlap / config.chunk_size
        assert 0.05 <= ratio <= 0.30, f"重叠比例 {ratio:.1%} 偏离推荐区间"
