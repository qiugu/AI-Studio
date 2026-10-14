"""无状态稀疏编码器（BM25 风格词权重）

为什么需要它
------------
现有检索是**单路稠密**。稠密向量擅长语义泛化，但对**精确词形**（编号、型号、
代码、专有名词、多语言混排片段）不敏感——这些片段在 embedding 空间里与查询的
距离未必最近，却往往是唯一正确的答案。混合检索通过引入词法分支补上这块短板。

实测边界（100 条真实查询 / 真实语料，详见
``docs/rag-eval/FIX-AND-HYBRID-RETRIEVAL-REPORT.md``）：增益是 **+1pp 量级**的
小幅提升，且集中在纯中文查询；「含数字/拉丁」分组上 Recall 提升、MRR/nDCG 略降。
不要指望混合检索带来数量级改善——真正的质量缺口在精排。

设计要点
--------
**查询侧零状态。** 这是本模块最重要的性质：文档权重（含 IDF 与长度归一化）
在**入库时**一次性算完并写进 Qdrant；查询向量是**词出现即为 1** 的二值向量，
不需要任何语料统计。因此：

* 默认（``idf=None``，即「无状态模式」）下，稀疏向量可**增量入库**——新增文档
  的编码与已有文档完全可比，无需重算历史向量；
* 若用 :meth:`SparseEncoder.fit` 注入 IDF 与语料平均长度，增益约高 30%，
  但**新增文档会使 df/avgdl 失效**，必须整库重编码才保持可比。生产默认取无状态。

词元化采用「ASCII 词 + 中文单字 + 中文二字组」：单字保证召回下限（任何查询词
都能命中），二字组补回少量词序信息（「模型训练」≠「训练模型」）。实测该组合
显著优于纯二字组（后者在短查询上漏召严重）。

索引空间与碰撞
--------------
Qdrant 稀疏向量要求下标为 ``uint32``。本模块用 CRC32 把词元映射到 32 位空间，
因此**没有词表**——这也正是查询侧不需要语料统计的原因。代价是理论上存在哈希
碰撞（数十万级词元规模下期望碰撞数为个位到十位量级），碰撞会把两个词元的权重
合并，产生极轻微的分数扰动。这是「零查询侧状态」换取的有意取舍；若某天需要
完全无碰撞，可改为「入库时持久化词表 + 查询时查表」，但那会把状态重新引入
查询路径。
"""

from __future__ import annotations

import math
import re
import zlib
from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

__all__ = [
    "SparseEncoder",
    "tokenize",
    "token_index",
    "DEFAULT_K1",
    "DEFAULT_B",
    "DEFAULT_AVGDL",
]

#: BM25 词频饱和参数。1.2 是文献与主流实现的默认值（Lucene/rank_bm25 同值）。
DEFAULT_K1 = 1.2
#: BM25 文档长度归一化强度。0.75 同为文献默认值。
DEFAULT_B = 0.75
#: 无状态模式下假定的语料平均长度（词元数）。
#: 取值依据：本项目 ``chunk_size`` 默认 448 字符，中文在「单字 + 二字组」下实测
#: 平均产出 487 词元（p50=539 / max=895），故取 490。该值只影响长度归一化的
#: 相对强度，BM25 对其不敏感（同一语料下所有文档共用同一分母）；且线上与评测
#: 路径实际使用的是 ``config.retrieval_sparse_avgdl``，此处仅为构造器的兜底默认。
#: **改 ``chunk_size`` 时应同步此值**，否则长文档的相对惩罚会偏离标定基准。
DEFAULT_AVGDL = 490.0

_ASCII = re.compile(r"[a-zA-Z0-9_]+")
_CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")


def tokenize(text: str) -> List[str]:
    """切分为 ASCII 词 + 中文单字 + 中文二字组

    Args:
        text: 原始文本

    Returns:
        词元列表（含重复，重复即词频）。ASCII 统一小写，中文保持原样。

    Note:
        **二字组只在同一段连续中文内部生成**。这一点与最初的可行性探针不同——
        探针先把全部中文字符收集成一个序列再两两配对，于是「检索 检索」会跨越
        空格造出无意义的「索检」，等于往查询与文档里都掺入噪声词元。此处改为
        按连续中文段（run）生成，语义更干净，且与「二字组用于补词序信息」这一
        初衷一致：跨段本来就不存在词序。

        只用正则做分词，不引入 jieba 等分词器：① 避免为一个分支新增重依赖；
        ② 分词器的词典版本变化会**静默改变所有历史向量的可比性**，对存量库
        是隐形的破坏。正则规则是稳定的。
    """
    if not text:
        return []
    lowered = text.lower()
    tokens = _ASCII.findall(lowered)
    for run in _CJK_RUN.findall(lowered):
        tokens.extend(run)  # 单字：保证任何查询词都有机会命中
        tokens.extend(a + b for a, b in zip(run, run[1:]))  # 二字组：补词序
    return tokens


def token_index(token: str) -> int:
    """词元 → ``uint32`` 稀疏下标（CRC32，稳定且无状态）"""
    return zlib.crc32(token.encode("utf-8")) & 0xFFFFFFFF


@dataclass
class SparseEncoder:
    """BM25 风格稀疏编码器

    Args:
        k1: 词频饱和参数
        b: 长度归一化强度
        avgdl: 文档平均长度（词元数），用于长度归一化
        idf: ``{token_index: idf}``。``None`` 表示**无状态模式**（IDF 恒为 1），
            此时同一文本在任意时刻、任意语料规模下编码结果完全一致，
            支持增量入库；非 ``None`` 时请仅通过 :meth:`fit` 构造，
            并注意语料变化后需整库重编码。

    Note:
        编码器本身是**不可变语义**的数据对象：``document_vector`` 只读取实例字段，
        无内部可变状态，因此可安全地跨线程共享（入库管线通常多线程/多进程）。
    """

    k1: float = DEFAULT_K1
    b: float = DEFAULT_B
    avgdl: float = DEFAULT_AVGDL
    idf: Optional[Mapping[int, float]] = None

    def _idf_of(self, index: int) -> float:
        if self.idf is None:
            return 1.0
        return self.idf.get(index, 1.0)

    # -- 文档侧：入库时调用一次，权重写入 Qdrant --------------------------

    def document_vector(self, text: str) -> Tuple[List[int], List[float]]:
        """编码文档为 ``(indices, values)``

        权重公式（与 `rank_bm25` / Lucene 的 BM25 一致）::

            w(t, d) = idf(t) · tf · (k1 + 1) / (tf + k1 · (1 − b + b · dl / avgdl))

        其中 ``dl`` 为该文档的词元总数，分母即 BM25 的词频饱和项：词频越高权重
        增长越慢，超过一定次数后趋于上限，避免「同一词刷几十遍」主导排序。
        """
        tokens = tokenize(text)
        if not tokens:
            return [], []

        counts: Dict[int, int] = {}
        for token in tokens:
            index = token_index(token)
            counts[index] = counts.get(index, 0) + 1

        doc_len = float(len(tokens))
        length_norm = self.k1 * (1.0 - self.b + self.b * doc_len / max(self.avgdl, 1e-9))
        saturation = self.k1 + 1.0

        indices: List[int] = []
        values: List[float] = []
        for index, tf in counts.items():
            denom = tf + length_norm
            if denom <= 0:
                continue
            weight = self._idf_of(index) * (tf * saturation) / denom
            if weight == 0.0:
                continue
            indices.append(index)
            values.append(float(weight))
        return indices, values

    # -- 查询侧：二值权重，不需要任何语料统计 ------------------------------

    def query_vector(self, text: str) -> Tuple[List[int], List[float]]:
        """编码查询为 ``(indices, values)``，值为 1.0（词出现即计一次）

        查询**不做**词频加权：同一词在查询里出现两次不代表相关性翻倍，
        且二值化使查询侧完全无需语料统计——这是查询侧零状态的来源。
        重复词元必须去重，否则打分时代码若按累加实现会等价于给了词频权重。

        Returns:
            下标升序、去重后的 ``(indices, values)``
        """
        tokens = tokenize(text)
        if not tokens:
            return [], []
        unique = sorted({token_index(token) for token in tokens})
        return unique, [1.0] * len(unique)

    # -- 语料拟合（离线/回填专用） ----------------------------------------

    @classmethod
    def fit(
        cls,
        texts: Sequence[str],
        *,
        k1: float = DEFAULT_K1,
        b: float = DEFAULT_B,
        with_idf: bool = True,
        avgdl: Optional[float] = None,
        sample_limit: Optional[int] = None,
    ) -> "SparseEncoder":
        """从语料统计 ``df`` 与 ``avgdl``，构造带 IDF 的编码器

        **仅用于离线回填与评测对照，不要用于在线增量入库**：新增文档会改变
        ``df`` 与 ``avgdl``，使已入库的稀疏权重与新建文档不再可比。

        Args:
            texts: 语料全文
            with_idf: ``False`` 时只统计 ``avgdl`` 而把 IDF 归为 1，
                用于「无状态 IDF + 语料长度」的对照实验
            avgdl: 直接指定平均长度；``None`` 表示由 ``texts`` 统计
            sample_limit: 只统计前 N 篇（大规模语料下的抽样近似，控制耗时）

        Returns:
            拟合后的编码器实例
        """
        corpus = list(texts[:sample_limit]) if sample_limit else list(texts)

        doc_freq: Dict[int, int] = {}
        lengths: List[int] = []
        for text in corpus:
            tokens = tokenize(text)
            lengths.append(len(tokens))
            for index in {token_index(token) for token in tokens}:
                doc_freq[index] = doc_freq.get(index, 0) + 1

        n_docs = len(corpus)
        computed_avgdl = (sum(lengths) / n_docs) if n_docs else DEFAULT_AVGDL

        idf: Optional[Dict[int, float]] = None
        if with_idf and n_docs:
            # 与 sklearn TfidfVectorizer(smooth_idf=True) 同式，保证与既有探针可比
            idf = {
                index: float(math.log(1.0 + (n_docs - df + 0.5) / (df + 0.5)))
                for index, df in doc_freq.items()
            }

        return cls(k1=k1, b=b, avgdl=float(avgdl or computed_avgdl), idf=idf)

    @property
    def is_stateless(self) -> bool:
        """是否为无状态模式（无 IDF，可增量入库）"""
        return self.idf is None


def default_encoder() -> SparseEncoder:
    """生产默认编码器（无状态）

    ``app.core.config`` 在导入期即读取环境变量（缺失必填项会直接抛错），因此这里
    **延迟导入**：让 ``app.utils.sparse`` 能被纯算法单测（不需要完整配置环境）单独
    import，而不是把配置的加载时机强加给所有使用者。
    """
    from app.core.config import config

    return SparseEncoder(
        k1=config.retrieval_sparse_k1,
        b=config.retrieval_sparse_b,
        avgdl=config.retrieval_sparse_avgdl,
        idf=None,
    )
