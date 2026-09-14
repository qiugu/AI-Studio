"""本地 CrossEncoder 精排（Reranker）。

精排解决的是稠密检索的**排序损失**：双塔（bi-encoder）把查询与文档分别编码，
两者直到最后一步才交互，因此对「字面相近但语义无关」的段落容易给高分。CrossEncoder
把 (query, passage) 拼成一个序列联合编码，能捕捉细粒度交互，代价是无法预计算文档向量、
只能在召回候选上做一次重排——所以必须配合「宽召回 + 精排」两段式使用。

设计约束
--------

1. **懒加载**：模型权重约 2 GB，进程启动时加载会拖慢服务冷启动，且未开启精排的
   部署不应承担这份内存。首次调用 ``rerank`` 时才加载，之后进程内复用。

2. **失败降级而非失败**：精排是**增强**，其不可用不应让检索整体失败。加载或推理
   异常统一抛出 :class:`RerankerUnavailable`，由调用方（``KnowledgeBaseService.search``）
   捕获并回落到纯稠密结果，同时记录日志。加载失败会被记忆，避免每个请求都重试一次
   昂贵的加载过程。

3. **可注入 encoder**：单测不应加载 2 GB 权重，也不应依赖真实模型输出。
   ``encoder`` 参数允许注入替身，使排序契约（分数降序、稳定、NaN 处理）可被独立验证。

4. **稳定排序**：分数相同时保持候选的原始顺序。精排模型对同分候选的相对次序没有
   语义承诺，若用不稳定的排序，同一输入可能得到不同顺序，评测结果将无法复现。
"""

from __future__ import annotations

import logging
import math
from typing import List, Optional, Protocol, Sequence, Tuple

from app.core.config import config

logger = logging.getLogger(__name__)

__all__ = [
    "RerankerUnavailable",
    "CrossEncoderReranker",
    "get_reranker",
    "reset_reranker_cache",
]

#: 单条文本的最大字符数兜底：模型自身按 token 截断，但超长字符串在进入
#: tokenizer 之前就会占用大量内存，这里是第二道防线。
_MAX_TEXT_CHARS = 20_000


class RerankerUnavailable(RuntimeError):
    """精排不可用（模型缺失、加载失败、推理异常）。

    调用方应捕获本异常并回落到纯稠密结果——精排是增强而非必需环节。
    """


class _Encoder(Protocol):
    """CrossEncoder 的最小接口，便于测试注入替身"""

    def predict(self, sentences: Sequence[Sequence[str]], **kwargs: object) -> Sequence[float]:
        ...


class CrossEncoderReranker:
    """本地 CrossEncoder 精排器

    Args:
        model_name: HuggingFace 模型 id 或本地路径
        device: 推理设备（cpu / mps / cuda）
        max_length: 输入截断长度（token）
        batch_size: 推理批大小
        encoder: 注入的 encoder 替身；为 ``None`` 时首次调用懒加载真实模型
    """

    def __init__(
        self,
        model_name: str = "BAAI/bge-reranker-v2-m3",
        device: str = "cpu",
        max_length: int = 512,
        batch_size: int = 32,
        encoder: Optional[_Encoder] = None,
    ) -> None:
        if not model_name or not model_name.strip():
            raise ValueError("model_name must be non-empty")
        if batch_size < 1:
            raise ValueError("batch_size must be >= 1")

        self.model_name = model_name
        self.device = device
        self.max_length = max_length
        self.batch_size = batch_size

        self._encoder = encoder
        self._load_error: Optional[str] = None

    # ── 模型加载 ────────────────────────────────────────────────────────────

    @property
    def is_loaded(self) -> bool:
        return self._encoder is not None

    @property
    def load_error(self) -> Optional[str]:
        return self._load_error

    def warmup(self) -> None:
        """显式加载模型，失败时抛 :class:`RerankerUnavailable`

        CLI 与启动自检应在处理任何请求之前调用它：把配置错误暴露在启动阶段，
        而不是等到第一条查询才失败。
        """
        self._ensure_encoder()

    def _ensure_encoder(self) -> _Encoder:
        """返回可用 encoder；加载失败时抛 :class:`RerankerUnavailable`

        失败结果会被记忆：``sentence-transformers`` 加载失败通常是权重缺失或
        依赖不完整这类**不会自愈**的原因，重试只会把故障成本乘以请求数。
        """
        if self._encoder is not None:
            return self._encoder
        if self._load_error is not None:
            raise RerankerUnavailable(self._load_error)

        try:
            from sentence_transformers import CrossEncoder
        except ImportError as exc:  # pragma: no cover - 依赖缺失属部署问题
            self._load_error = (
                "sentence-transformers is not installed; reranking disabled"
            )
            raise RerankerUnavailable(self._load_error) from exc

        try:
            self._encoder = CrossEncoder(
                self.model_name, device=self.device, max_length=self.max_length
            )
        except Exception as exc:  # noqa: BLE001 - 任何加载失败都必须降级而非中断检索
            self._load_error = f"failed to load reranker {self.model_name}: {exc}"
            logger.warning("%s (device=%s)", self._load_error, self.device)
            raise RerankerUnavailable(self._load_error) from exc

        logger.info("Loaded reranker %s on device=%s", self.model_name, self.device)
        return self._encoder

    # ── 推理 ────────────────────────────────────────────────────────────────

    @staticmethod
    def _normalize_query(query: str) -> str:
        return (query or "").strip()

    @classmethod
    def _clip(cls, text: str) -> str:
        return text if len(text) <= _MAX_TEXT_CHARS else text[:_MAX_TEXT_CHARS]

    def score(self, query: str, passages: Sequence[str]) -> List[float]:
        """对 ``(query, passage)`` 逐对打分，返回与 ``passages`` 等长的分数列表"""
        if not passages:
            return []

        encoder = self._ensure_encoder()
        pairs = [
            [self._normalize_query(query), self._clip(passage or "")]
            for passage in passages
        ]
        try:
            raw = encoder.predict(pairs, batch_size=self.batch_size, show_progress_bar=False)
        except Exception as exc:  # noqa: BLE001 - 推理异常同样必须降级
            raise RerankerUnavailable(f"reranker inference failed: {exc}") from exc

        scores = [float(value) for value in raw]
        if len(scores) != len(passages):
            raise RerankerUnavailable(
                f"reranker returned {len(scores)} scores for {len(passages)} passages"
            )

        # NaN 会把「按分数降序」变成未定义行为（比较全部为 False，排序结果取决于
        # 实现细节）。将其压到最低分并记录，保证排序仍然确定。
        if any(math.isnan(value) for value in scores):
            logger.warning("reranker produced NaN scores; coerced to -inf")
            scores = [value if not math.isnan(value) else float("-inf") for value in scores]
        return scores

    def rerank(
        self,
        query: str,
        candidates: Sequence[Tuple[str, str]],
    ) -> List[Tuple[str, float]]:
        """对 ``[(id, text), ...]`` 重排，返回按分数降序的 ``[(id, score), ...]``

        Note:
            返回结果与输入候选**一一对应**（不增不减）；丢弃候选项会让召回指标
            无故下降且极难排查，覆盖/去重应由调用方按业务语义决定。
        """
        if not candidates:
            return []

        ids = [item[0] for item in candidates]
        texts = [item[1] for item in candidates]
        scores = self.score(query, texts)

        # 稳定排序：同分保持候选原顺序，保证同一输入得到同一输出。
        order = sorted(range(len(ids)), key=lambda index: (-scores[index], index))
        return [(ids[index], scores[index]) for index in order]


# ── 进程级单例 ──────────────────────────────────────────────────────────────

_reranker: Optional[CrossEncoderReranker] = None


def get_reranker(
    model_name: Optional[str] = None,
    device: Optional[str] = None,
    max_length: Optional[int] = None,
    batch_size: Optional[int] = None,
) -> CrossEncoderReranker:
    """获取进程级精排器单例（参数缺省时取全局配置）

    单例的意义在于模型加载成本：``CrossEncoder`` 每次实例化都会读取全部权重，
    在请求路径上反复构造会直接拖垮吞吐。
    """
    global _reranker
    if _reranker is None:
        _reranker = CrossEncoderReranker(
            model_name=model_name or config.reranker_model,
            device=device or config.reranker_device,
            max_length=max_length or config.reranker_max_length,
            batch_size=batch_size or config.reranker_batch_size,
        )
    return _reranker


def reset_reranker_cache() -> None:
    """清空单例（测试与配置变更后使用）"""
    global _reranker
    _reranker = None
