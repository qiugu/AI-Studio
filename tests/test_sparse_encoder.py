"""无状态稀疏编码器的契约

覆盖四类性质，每一条都对应一个具体的工程风险：

1. **词元化**：ASCII 词统一小写 + 中文单字 + 中文二字组。单字与二字组缺一不可——
   只有二字组时短查询会大面积漏召，只有单字时丢失词序。
2. **BM25 权重**：词频饱和（同一词刷 N 遍不得让权重线性增长）与长度归一化
   （长文档不得因为「什么词都有一点」而占优）。
3. **无状态性（最要紧）**：同一文本的编码结果必须与**其他文档无关**。这是
   「可增量入库」的前提——若编码依赖语料统计，新增一篇文档就会让历史向量
   全体失配，且**不会有任何报错**，只会静默降低检索质量。
4. **查询侧去重**：查询词在文本里出现两次不等于相关度翻倍；且查询向量必须是
   二值的，否则查询侧就要依赖语料统计，第 3 条随之破产。
"""

from __future__ import annotations

import pytest

from app.utils.sparse import (
    DEFAULT_AVGDL,
    SparseEncoder,
    token_index,
    tokenize,
)


class TestTokenization:
    def test_ascii_words_lowercased_and_kept_whole(self):
        """ASCII 词/数字保持整体并小写化——它们是编号、型号、代码的主要载体"""
        tokens = tokenize("BGE-M3 1024 Transformer")
        assert "bge" in tokens
        assert "m3" in tokens
        assert "1024" in tokens
        assert "transformer" in tokens
        # 不应把 bge 再拆成单字母
        assert "b" not in tokens

    def test_chinese_unigrams_are_present(self):
        """中文单字必须在词元集合里：这是短查询的召回下限保障"""
        tokens = tokenize("向量检索")
        for char in "向量检索":
            assert char in tokens

    def test_chinese_bigrams_preserve_word_order(self):
        """二字组用于区分「模型训练」与「训练模型」这类同字异序片段"""
        assert "模型" in tokenize("模型训练")
        assert "训练" in tokenize("模型训练")
        forward = set(tokenize("模型训练"))
        backward = set(tokenize("训练模型"))
        assert forward != backward

    def test_bigrams_do_not_cross_ascii_boundaries(self):
        """中文二字组不能跨越 ASCII 片段拼接，否则会造出无意义词元"""
        tokens = tokenize("中文abc中文")
        # 两个中文块各自成字，不应产生「文a」「c中」之类
        assert "文a" not in tokens
        assert "c中" not in tokens

    def test_empty_and_whitespace_input(self):
        assert tokenize("") == []
        assert tokenize("   ") == []
        # 纯标点：ASCII 词与 CJK 都为空
        assert tokenize("！？，。") == []

    def test_token_index_is_stable_and_uint32(self):
        """下标必须稳定（跨进程一致）且在 uint32 范围内——Qdrant 的硬约束"""
        assert token_index("向量") == token_index("向量")
        value = token_index("向量")
        assert 0 <= value <= 0xFFFFFFFF
        assert token_index("向量") != token_index("检索")


class TestBm25Weights:
    def test_term_frequency_saturates(self):
        """词频饱和：出现 10 次不得得到 10 倍权重（否则刷词即可操纵排序）"""
        encoder = SparseEncoder()
        target = token_index("检")
        once = dict(zip(*encoder.document_vector("检")))
        ten = dict(zip(*encoder.document_vector("检" * 10)))
        assert ten[target] > once[target]
        assert ten[target] < once[target] * 10, "词频未被饱和，BM25 退化为 TF"

    def test_weights_are_positive(self):
        encoder = SparseEncoder()
        _, values = encoder.document_vector("向量检索与混合检索")
        assert values and all(value > 0 for value in values)

    def test_longer_document_gets_lower_weight_per_occurrence(self):
        """长度归一化：同样出现一次的同一个词，在长文档中权重应更低"""
        encoder = SparseEncoder(avgdl=20.0)
        target = token_index("检")
        short = dict(zip(*encoder.document_vector("检")))
        long_doc = dict(zip(*encoder.document_vector("检" + "填" * 100)))
        assert short[target] > long_doc[target], "长文档未因长度而归一化降权"

    def test_empty_text_yields_empty_vector(self):
        encoder = SparseEncoder()
        assert encoder.document_vector("") == ([], [])
        assert encoder.document_vector("，。！") == ([], [])

    def test_indices_are_unique_per_document(self):
        """同一文档内一个下标只能出现一次——重复下标会构成非法的 Qdrant 稀疏向量"""
        encoder = SparseEncoder()
        indices, values = encoder.document_vector("检索检索检索向量向量")
        assert len(indices) == len(set(indices))
        assert len(indices) == len(values)


class TestStateless:
    def test_same_text_encodes_identically_across_instances(self):
        """默认编码器不含任何语料状态，两个实例必须给出逐位相同的结果"""
        text = "向量检索的混合策略与加权分数融合"
        assert SparseEncoder().document_vector(text) == SparseEncoder().document_vector(text)

    def test_encoding_is_independent_of_other_documents(self):
        """**增量入库的核心契约**：编码一篇文档不得依赖其它文档

        若本条失败，说明编码器引入了语料统计（df/avgdl），那么新增文档会让
        历史向量全体失配——且不发一言。
        """
        text = "检索增强生成"
        before = SparseEncoder().document_vector(text)
        # 模拟「语料里后来又加了很多文档」：编码器本身不应感知到
        for _ in range(50):
            SparseEncoder().document_vector("完全无关的另一段长文本用于干扰")
        after = SparseEncoder().document_vector(text)
        assert before == after

    def test_is_stateless_flag(self):
        assert SparseEncoder().is_stateless is True
        assert SparseEncoder.fit(["a b c", "a"]).is_stateless is False

    def test_default_avgdl_is_used_when_unspecified(self):
        assert SparseEncoder().avgdl == DEFAULT_AVGDL


class TestQueryVector:
    def test_query_values_are_binary(self):
        indices, values = SparseEncoder().query_vector("检索 检索 向量")
        assert set(values) == {1.0}
        assert indices and len(indices) == len(values)

    def test_query_terms_are_deduplicated(self):
        """重复词元必须去重：否则等价于给该词加上了词频权重

        这条同时守护「二字组不跨段生成」：若二字组跨空格配对，「检索 检索 检索」
        会多出「索检」这一噪声词元，与单次「检索」的向量不再相同。
        """
        once = SparseEncoder().query_vector("检索")[0]
        thrice = SparseEncoder().query_vector("检索 检索 检索")[0]
        assert once == thrice

    def test_query_indices_are_sorted_ascending(self):
        """下标升序是确定性的一部分：保证同一查询在不同进程产出相同向量"""
        indices, _ = SparseEncoder().query_vector("混合检索 hybrid retrieval 2026")
        assert indices == sorted(indices)

    def test_empty_query_yields_empty_vector(self):
        assert SparseEncoder().query_vector("") == ([], [])
        assert SparseEncoder().query_vector("？。！") == ([], [])

    def test_query_and_document_share_index_space(self):
        """查询与文档必须使用同一下标空间，否则永远匹配不上"""
        encoder = SparseEncoder()
        doc_indices, _ = encoder.document_vector("向量检索")
        query_indices, _ = encoder.query_vector("向量")
        assert set(query_indices).issubset(set(doc_indices))


class TestFitMode:
    def test_rare_terms_get_higher_idf(self):
        """``fit`` 模式下稀有词 IDF 更高——这是它比无状态模式多出的那部分增益"""
        corpus = ["常见词 常见词 常见词 稀有词", "常见词 常见词", "常见词"]
        encoder = SparseEncoder.fit(corpus)
        common = token_index("常见")
        rare = token_index("稀有")
        assert encoder.idf is not None
        assert encoder.idf[rare] > encoder.idf[common]

    def test_fit_computes_avgdl_from_corpus(self):
        encoder = SparseEncoder.fit(["a b c d", "a b"])
        assert encoder.avgdl == pytest.approx((4 + 2) / 2)

    def test_fit_without_idf_keeps_avgdl_only(self):
        encoder = SparseEncoder.fit(["a b c", "a"], with_idf=False)
        assert encoder.idf is None
        assert encoder.is_stateless is True

    def test_fit_on_empty_corpus_does_not_crash(self):
        encoder = SparseEncoder.fit([])
        assert encoder.avgdl == DEFAULT_AVGDL
        assert encoder.idf is None

    def test_fit_changes_weights_relative_to_stateless(self):
        """对照成立：两种模式的权重必须真的不同，否则「IDF 增益」无从谈起"""
        corpus = ["常见词 常见词 稀有词", "常见词", "常见词", "常见词"]
        target = token_index("稀有")
        stateless_map = dict(
            zip(*SparseEncoder(avgdl=10.0).document_vector("常见词 常见词 稀有词"))
        )
        fitted_map = dict(
            zip(*SparseEncoder.fit(corpus, avgdl=10.0).document_vector("常见词 常见词 稀有词"))
        )
        assert target in stateless_map and target in fitted_map
        assert stateless_map[target] != fitted_map[target]

    def test_sample_limit_restricts_statistics_window(self):
        encoder = SparseEncoder.fit(["a b c", "a b c", "x"], sample_limit=1)
        assert encoder.avgdl == pytest.approx(3.0)
