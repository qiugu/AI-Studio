"""检索器实现：离线确定性、端到端真实链路、可插拔重排

三种实现服务于不同目的，**不可互相替代**：

======================  ==================  ==========================================
实现                     是否需要外部服务      用途
======================  ==================  ==========================================
``InMemoryRetriever``   否                  单测与 CI。用确定性哈希向量，结果逐位可复现，
                                            验证的是**评测框架本身**的正确性，不代表检索质量。
``QdrantRetriever``     是（Qdrant）        端到端真实链路，产出可对外引用的指标。
``RerankedRetriever``   取决于被包装者        装饰器：宽召回 + 精排，用于度量重排增益。
======================  ==================  ==========================================

**口径一致性（不可妥协）**：``QdrantRetriever`` 必须经由
:func:`app.core.vector_db.search_points` 完成召回，与线上
``KnowledgeBaseService.search()`` 共用同一实现。一旦评测侧另写一份 Qdrant 查询逻辑，
评测结论就不能再用来推断线上行为——这是评测体系最常见的失效方式。
"""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

from app.core.config import config
from app.core.vector_db import RetrievedPoint, search_points

__all__ = [
    "RetrievalResult",
    "Retriever",
    "InMemoryRetriever",
    "QdrantRetriever",
    "RerankedRetriever",
    "PassageMappedRetriever",
    "TextLookup",
    "RerankFn",
]

#: 检索单元 id → 文本。重排与切断检测都需要原文，但不应为此让评测依赖 MySQL：
#: 语料在采样入库时已确定，映射关系由索引清单提供。
TextLookup = Callable[[str], Optional[str]]

#: ``(query, [(id, text), ...]) -> [(id, score), ...]``，返回按分数降序的结果。
RerankFn = Callable[[str, Sequence[Tuple[str, str]]], List[Tuple[str, float]]]

_EMBED_DIM = 512
_TOKEN_PATTERN = re.compile(r"[a-zA-Z0-9_]+|[\u4e00-\u9fff]")
_CJK = re.compile(r"[\u4e00-\u9fff]")


@dataclass
class RetrievalResult:
    """一次检索的完整产物

    ``candidate_ids`` 与 ``ids`` 的关系是评测的关键：前者是宽召回集合
    （``candidate_k``），后者是最终返回集合（``top_k``）。有了两者才能把
    「召回损失」与「排序损失」分开度量——只报一个 Recall@k 无法说明问题是
    召回没捞到，还是捞到了但排太后。
    """

    ids: List[str] = field(default_factory=list)
    scores: List[float] = field(default_factory=list)
    candidate_ids: Optional[List[str]] = None
    candidate_scores: Optional[List[float]] = None
    retrieve_latency_ms: float = 0.0
    rerank_latency_ms: Optional[float] = None

    @property
    def top1(self) -> Optional[str]:
        return self.ids[0] if self.ids else None


class Retriever:
    """检索器接口

    子类只需实现 :meth:`retrieve`。``name`` 用于报告中的分组标识。
    """

    name: str = "retriever"

    def retrieve(self, query: str, top_k: int) -> RetrievalResult:  # pragma: no cover - 抽象
        raise NotImplementedError


# ── 离线确定性实现 ──────────────────────────────────────────────────────────


class InMemoryRetriever(Retriever):
    """内存检索器：确定性特征哈希 + 余弦相似度

    用途是**验证评测框架的正确性**，而非度量检索质量：

    * 完全离线、无网络、无模型权重，可在任意环境（含 CI）稳定运行；
    * 向量由 md5 特征哈希生成，不使用随机数，同一输入永远得到同一排序；
    * 采用词/字双粒度 + IDF 加权，使「词面重叠高者得分高」，因此可以对
      「相关结果应排第一」这类断言给出有意义的期望值，而不是只能断言
      「返回了 k 条」。

    它**不**构成任何质量基线，报告中的质量结论不得引用本实现。
    """

    def __init__(
        self,
        corpus: Dict[str, str],
        dim: int = _EMBED_DIM,
        name: str = "in-memory-hash",
    ) -> None:
        if dim < 1:
            raise ValueError("dim must be >= 1")
        self.name = name
        self.dim = dim
        self._ids: List[str] = list(corpus.keys())
        self._vectors = self._build_vectors(corpus)

    # -- 向量化 -------------------------------------------------------------

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        """切分为英文单词/数字 + 中文字符，并补中文二字组以保留少量词序信息"""
        tokens = _TOKEN_PATTERN.findall(text.lower())
        bigrams = [
            first + second
            for first, second in zip(tokens, tokens[1:])
            if _CJK.match(first) and _CJK.match(second)
        ]
        return tokens + bigrams

    @staticmethod
    def _bucket(token: str, dim: int) -> Tuple[int, float]:
        """特征哈希：下标由 md5 决定，符号由另一个 bit 决定（带符号哈希降低碰撞偏差）"""
        digest = hashlib.md5(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dim
        sign = 1.0 if digest[4] & 1 else -1.0
        return index, sign

    def _build_vectors(self, corpus: Dict[str, str]) -> np.ndarray:
        tokenized = {doc_id: self._tokenize(text) for doc_id, text in corpus.items()}

        # IDF：让「到处都出现的词」权重下降，否则高频虚词会主导相似度
        doc_freq: Dict[str, int] = {}
        for tokens in tokenized.values():
            for token in set(tokens):
                doc_freq[token] = doc_freq.get(token, 0) + 1
        n_docs = max(len(tokenized), 1)

        vectors = np.zeros((len(self._ids), self.dim), dtype=np.float32)
        for row, doc_id in enumerate(self._ids):
            for token in tokenized[doc_id]:
                index, sign = self._bucket(token, self.dim)
                idf = 1.0 + np.log((1 + n_docs) / (1 + doc_freq.get(token, 0)))
                vectors[row, index] += sign * idf
            norm = float(np.linalg.norm(vectors[row]))
            if norm > 0:
                vectors[row] /= norm
        return vectors

    def embed(self, text: str) -> np.ndarray:
        """对任意文本编码为同空间向量（与语料向量使用同一哈希方案）"""
        vector = np.zeros(self.dim, dtype=np.float32)
        for token in self._tokenize(text):
            index, sign = self._bucket(token, self.dim)
            vector[index] += sign
        norm = float(np.linalg.norm(vector))
        return vector / norm if norm > 0 else vector

    # -- 检索 ---------------------------------------------------------------

    def retrieve(self, query: str, top_k: int) -> RetrievalResult:
        started = time.perf_counter()
        query_vector = self.embed(query)
        scores = self._vectors @ query_vector
        order = np.argsort(-scores, kind="stable")[:top_k]
        elapsed_ms = (time.perf_counter() - started) * 1000.0

        ids = [self._ids[i] for i in order]
        return RetrievalResult(
            ids=ids,
            scores=[float(scores[i]) for i in order],
            retrieve_latency_ms=elapsed_ms,
        )


# ── 端到端真实链路 ──────────────────────────────────────────────────────────


class QdrantRetriever(Retriever):
    """通过线上同一实现 ``search_points`` 访问真实 Qdrant

    Args:
        collection_name: 形如 ``kb_{kb_id}``
        embed_fn: ``query -> List[float]``；默认使用与线上一致的 EmbeddingClient
        score_threshold: 缺省取 ``config.retrieval_score_threshold``，与线上默认一致
        query_filter: 可选 Qdrant Filter
        client: 可注入客户端（测试用）
    """

    def __init__(
        self,
        collection_name: str,
        embed_fn: Optional[Callable[[str], Sequence[float]]] = None,
        score_threshold: Optional[float] = None,
        query_filter: Optional[object] = None,
        client: Optional[object] = None,
        name: Optional[str] = None,
    ) -> None:
        self.collection_name = collection_name
        self._embed_fn = embed_fn
        self.score_threshold = (
            score_threshold if score_threshold is not None else config.retrieval_score_threshold
        )
        self.query_filter = query_filter
        self._client = client
        self.name = name or f"qdrant:{collection_name}"

    def _embed(self, query: str) -> Sequence[float]:
        if self._embed_fn is not None:
            return self._embed_fn(query)
        # 延迟导入：默认路径需要真实模型依赖，离线单测不会走到这里
        from app.utils.embedding import get_embedding_client

        return get_embedding_client().embed([query])[0]

    def retrieve(self, query: str, top_k: int) -> RetrievalResult:
        started = time.perf_counter()
        points: List[RetrievedPoint] = search_points(
            collection_name=self.collection_name,
            query_vector=self._embed(query),
            limit=top_k,
            score_threshold=self.score_threshold,
            query_filter=self.query_filter,
            client=self._client,
        )
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return RetrievalResult(
            ids=[point.id for point in points],
            scores=[point.score for point in points],
            retrieve_latency_ms=elapsed_ms,
        )


# ── 重排装饰器 ──────────────────────────────────────────────────────────────


class RerankedRetriever(Retriever):
    """宽召回 + 精排

    先用被包装的检索器取 ``candidate_k`` 条候选（**不设阈值**，交给精排裁量），
    再把候选原文交给 ``rerank_fn`` 重新打分，最终截断到 ``top_k``。

    精排函数通过参数注入而非在此实现，原因有二：Phase 1 需在无模型依赖的环境
    下完成框架单测；Phase 3 接入本地 CrossEncoder 时无需改动本类的任何逻辑。

    Args:
        base: 被包装的检索器（提供宽召回）
        rerank_fn: ``(query, [(id, text)]) -> [(id, score)]``
        text_lookup: ``id -> 文本``；缺失文本的候选**保留原有相对顺序并排在重排结果之后**，
            既不丢弃也不臆造分数（静默丢弃会让 Recall 无故下降且难以排查）
        candidate_k: 宽召回条数，默认 20
    """

    def __init__(
        self,
        base: Retriever,
        rerank_fn: RerankFn,
        text_lookup: TextLookup,
        candidate_k: int = 20,
        name: Optional[str] = None,
    ) -> None:
        if candidate_k < 1:
            raise ValueError("candidate_k must be >= 1")
        self.base = base
        self.rerank_fn = rerank_fn
        self.text_lookup = text_lookup
        self.candidate_k = candidate_k
        self.name = name or f"reranked({base.name})"

    def retrieve(self, query: str, top_k: int) -> RetrievalResult:
        candidates = self.base.retrieve(query, top_k=max(self.candidate_k, top_k))
        candidate_scores = dict(zip(candidates.ids, candidates.scores))

        resolvable: List[Tuple[str, str]] = []
        unresolvable: List[str] = []
        for doc_id in candidates.ids:
            text = self.text_lookup(doc_id)
            if text is None:
                unresolvable.append(doc_id)
            else:
                resolvable.append((doc_id, text))

        started = time.perf_counter()
        ordered: List[Tuple[str, float]] = []
        if resolvable:
            # 防御：精排实现可能漏掉或重复返回候选项，此处只接受已知候选
            known = {doc_id for doc_id, _ in resolvable}
            seen: set[str] = set()
            for doc_id, score in self.rerank_fn(query, resolvable):
                if doc_id in known and doc_id not in seen:
                    seen.add(doc_id)
                    ordered.append((doc_id, float(score)))
            # 精排未覆盖的候选项按原顺序补回尾部，保证不因实现疏漏而丢结果
            ordered.extend(
                (doc_id, candidate_scores.get(doc_id, 0.0))
                for doc_id, _ in resolvable
                if doc_id not in seen
            )
        # 缺原文的候选既不丢弃也不臆造分数，按原相关度顺序排在最后
        ordered.extend((doc_id, candidate_scores.get(doc_id, 0.0)) for doc_id in unresolvable)
        rerank_ms = (time.perf_counter() - started) * 1000.0

        final = ordered[:top_k]
        return RetrievalResult(
            ids=[doc_id for doc_id, _ in final],
            scores=[score for _, score in final],
            candidate_ids=list(candidates.ids),
            candidate_scores=list(candidates.scores),
            retrieve_latency_ms=candidates.retrieve_latency_ms,
            rerank_latency_ms=rerank_ms,
        )


# ── 分块 → 段落映射 ─────────────────────────────────────────────────────────


class PassageMappedRetriever(Retriever):
    """把分块级检索结果映射到段落级并去重

    为什么需要：基准的标准答案是**段落**，而索引单元是**分块**（一个段落可能被
    ``TextSplitter`` 切成多块）。若直接按分块打分：

    * 同一段落的多个分块会同时占据 top-k，挤掉其他段落的召回机会；
    * Recall 的分母会随分块参数变化——Phase 5 正要调整 ``chunk_size``，
      那样本次结果就再也无法与之比较。

    因此在整个检索链路的**最外层**做映射：宽召回与精排仍作用在分块上（与线上一致），
    只有最终排序结果被折叠到段落粒度。折叠时保留每个段落的首次出现位置，即
    「该段落最好分块的排名」，这与「段落是否被检索到、排在第几」的语义一致。

    Args:
        base: 被包装的检索器（返回分块级结果）
        id_map: ``{point_id: passage_id}``，来自索引构建期（``chunks.jsonl``）
        oversample: 向底层索取的倍数。去重必然使列表变短，索取 ``top_k`` 条可能
            去重后不足 ``top_k``。本语料实测约 1.47 块/段落，取 5 足以覆盖长尾。
        max_fetch: 单次索取的硬上限，避免超长 top_k 触发无意义的深召回。
    """

    def __init__(
        self,
        base: Retriever,
        id_map: Dict[str, str],
        oversample: int = 5,
        max_fetch: int = 2000,
        name: Optional[str] = None,
    ) -> None:
        if oversample < 1:
            raise ValueError("oversample must be >= 1")
        if max_fetch < 1:
            raise ValueError("max_fetch must be >= 1")
        self.base = base
        self.id_map = id_map
        self.oversample = oversample
        self.max_fetch = max_fetch
        self.name = name or f"passage({base.name})"
        self._unmapped_seen: set[str] = set()

    def _fold(self, ids: Sequence[str]) -> List[str]:
        """按原顺序映射为段落 id 并去重（保留首次出现位置）"""
        folded: List[str] = []
        seen: set[str] = set()
        for raw_id in ids:
            passage_id = self.id_map.get(raw_id)
            if passage_id is None:
                # 索引与清单不一致。不静默丢弃：保留原 id 让它在评测中自然落空，
                # 这样问题会以「Recall 偏低」显式暴露，而不是被悄悄抹平。
                self._unmapped_seen.add(raw_id)
                passage_id = raw_id
            if passage_id in seen:
                continue
            seen.add(passage_id)
            folded.append(passage_id)
        return folded

    @property
    def unmapped_count(self) -> int:
        """未能在清单中找到映射的检索单元数量（索引漂移的信号）"""
        return len(self._unmapped_seen)

    def retrieve(self, query: str, top_k: int) -> RetrievalResult:
        fetch_k = min(self.max_fetch, max(top_k, top_k * self.oversample))
        raw = self.base.retrieve(query, top_k=fetch_k)

        # 分块 → 段落；分数取该段落最好分块的分数（首次出现者）
        best_score: Dict[str, float] = {}
        for raw_id, score in zip(raw.ids, raw.scores):
            passage_id = self.id_map.get(raw_id, raw_id)
            best_score.setdefault(passage_id, score)

        folded_ids = self._fold(raw.ids)[:top_k]
        candidate_ids = self._fold(raw.candidate_ids) if raw.candidate_ids else None
        candidate_scores = None
        if candidate_ids is not None and raw.candidate_scores:
            candidate_scores = [
                best_score.get(passage_id, 0.0) for passage_id in candidate_ids
            ]

        return RetrievalResult(
            ids=folded_ids,
            scores=[best_score.get(passage_id, 0.0) for passage_id in folded_ids],
            candidate_ids=candidate_ids,
            candidate_scores=candidate_scores,
            retrieve_latency_ms=raw.retrieve_latency_ms,
            rerank_latency_ms=raw.rerank_latency_ms,
        )
