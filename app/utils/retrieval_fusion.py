"""混合检索的分数融合（**唯一实现**，线上与离线评测必须共用）

为什么必须只有一个实现
----------------------
融合策略决定了「稠密分支」与「词法分支」的相对话语权。若线上与评测各写一份，
两者的 α 语义、归一化范围、并列处理都会悄悄分叉，评测结论随即失去对线上的
推断力——这是检索评测体系最典型的失效方式。因此本模块是融合的**唯一入口**：
``KnowledgeBaseService.search_with_diagnostics`` 与
``app.rag_eval.retrievers.HybridRetriever`` 都调用 :func:`weighted_fuse`。

为什么不用 RRF（重要，且与直觉相反）
------------------------------------
「用 RRF 做混合检索」是社区默认做法，但在本项目语料上**实测有害**：
等权 RRF 使 MRR@10 −7.33pp、nDCG@10 −6.03pp。原因是两个分支强弱悬殊
（词法分支单独使用时 Recall@5 比稠密低 14.8pp），RRF 只看排名不看分数，
等于把弱分支的噪声排名与强分支同等对待，把稠密的正确项挤下去。
加权 RRF（10:1）也只能把损失压到 −0.94pp，仍无法转正。

**只有「归一化分数融合 + 稠密主导」能带来正增益**，且 α 在 0.6/0.7/0.8 三点
均为正——说明增益不是刀刃式调参的产物。

并列（tie）的处置
-----------------
按「稠密分支排名优先、稠密独有项次之、词法独有项最后」的稳定顺序落位。
理由是稠密分支在本语料上更强，并列时让它先占位是更大概率正确的选择，
且该规则**确定性可复现**（不依赖字典遍历顺序）。
"""

from __future__ import annotations

from typing import Dict, List, Sequence, Tuple

__all__ = ["minmax_normalize", "weighted_fuse"]


def minmax_normalize(scores: Sequence[float]) -> List[float]:
    """把分数线性映射到 ``[0, 1]``

    为什么必须归一化：稠密余弦相似度的典型区间是 ``0.4~0.9``，而 BM25 分数
    无上界（取决于语料与查询词数，可为数十）。若直接加权相加，BM25 的绝对值
    尺度会完全压过稠密分数，α 就失去调节意义。

    边界行为（**有意选择，不是疏漏**）：

    * 空列表 → 空列表；
    * 全部相等（含单元素）→ 全部返回 ``1.0``。此时「相对顺序无信息」，
      映射为 0.0 会让该分支整体退出融合；映射为 1.0 则让它与另一分支的
      最高分候选并列，由 :func:`weighted_fuse` 的并列规则裁量。后者更保守：
      不会因为「这一路只召回了 1 条」就把这一条判为无关。
    """
    if not scores:
        return []
    lo, hi = min(scores), max(scores)
    if hi - lo < 1e-12:
        return [1.0 for _ in scores]
    return [(float(value) - lo) / (hi - lo) for value in scores]


def weighted_fuse(
    dense_ids: Sequence[str],
    dense_scores: Sequence[float],
    sparse_ids: Sequence[str],
    sparse_scores: Sequence[float],
    alpha: float,
) -> List[Tuple[str, float]]:
    """加权分数融合，返回按融合分数降序的 ``(id, fused_score)``

    ``fused(id) = α · norm(dense)(id) + (1 − α) · norm(sparse)(id)``；
    只在一侧出现的 id 只累加该侧的贡献（缺失的一侧按 0 计，等价于「该分支
    认为它完全不相关」）。

    Args:
        dense_ids: 稠密分支召回 id，按相似度降序
        dense_scores: 与 ``dense_ids`` 等长的相似度
        sparse_ids: 词法分支召回 id，按 BM25 得分降序
        sparse_scores: 与 ``sparse_ids`` 等长
        alpha: 稠密分支权重，``0.0~1.0``。实测最优 0.7；
            α=1.0 退化为纯稠密（可用于开关关闭时的等价性验证）

    Returns:
        ``[(id, fused_score), ...]``，融合分数降序；并列时依
        「稠密先、词法后」的稳定顺序。

    Raises:
        ValueError: ``alpha`` 越界，或 id/scores 长度不一致。
            这类错误必须显式失败：静默截断会让融合结果偏移而不被察觉。
    """
    if not 0.0 <= alpha <= 1.0:
        raise ValueError(f"alpha must be within [0, 1], got {alpha}")
    if len(dense_ids) != len(dense_scores):
        raise ValueError(
            f"dense ids/scores length mismatch: {len(dense_ids)} != {len(dense_scores)}"
        )
    if len(sparse_ids) != len(sparse_scores):
        raise ValueError(
            f"sparse ids/scores length mismatch: {len(sparse_ids)} != {len(sparse_scores)}"
        )
    if alpha == 1.0:
        # 快路径：纯稠密。既省一次归一化，也用于验证「关闭混合检索时行为等价」。
        return [(doc_id, float(score)) for doc_id, score in zip(dense_ids, dense_scores)]
    if alpha == 0.0:
        return [(doc_id, float(score)) for doc_id, score in zip(sparse_ids, sparse_scores)]

    fused: Dict[str, float] = {}
    order: List[str] = []

    for doc_id, norm in zip(dense_ids, minmax_normalize(dense_scores)):
        if doc_id not in fused:
            order.append(doc_id)
            fused[doc_id] = 0.0
        fused[doc_id] += alpha * norm

    for doc_id, norm in zip(sparse_ids, minmax_normalize(sparse_scores)):
        if doc_id not in fused:
            order.append(doc_id)
            fused[doc_id] = 0.0
        fused[doc_id] += (1.0 - alpha) * norm

    # ``order`` 已保证「稠密集合在前、稠密独有项其次、词法独有项最后」；
    # Python 的 sorted 稳定，故并列时该顺序被保留 —— 不要在 key 里再加次键，
    # 否则会把「稠密优先」这一有意选择覆盖成字典序。
    ranked = sorted(order, key=lambda doc_id: -fused[doc_id])
    return [(doc_id, fused[doc_id]) for doc_id in ranked]
