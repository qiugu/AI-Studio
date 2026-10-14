"""检索质量指标（纯函数，无外部依赖）

口径遵循 BEIR / MTEB / RAGAS 的通行定义，两条不可妥协的约束：

1. **Recall / MAP 的分母一律取「完整相关集」**（``|R|``），不得使用 ``top_k``
   截断后的集合，否则 Recall 会被系统性高估——这是检索评测中最常见的口径错误。
2. **排序类指标在截断位置 k 处停止累加**，未命中记 0；命中位置 ``rank`` 从 1 开始。

设计约定：

* 输入 ``retrieved`` 为「按相关度降序排列」的检索结果 ID 序列（第 0 个即 rank=1）。
* 输入序列中的重复 ID 会被**去重并保留首次出现位置**，避免同一文档占据多个名次
  导致指标被虚高。
* ``relevant`` 为空表示「该查询无标准答案」，此时指标无定义；本模块**显式抛错**
  而不返回 0 或 1，以免把「标注缺失」静默混入平均值。跳过这类查询由调用方
  （``runner``）负责决策并记录 ``n_scored``。

所有函数均为纯函数，不读写状态、不访问网络，可直接用于离线回归门禁。
"""

from math import log2
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

__all__ = [
    "DEFAULT_KS",
    "recall_at_k",
    "hit_at_k",
    "precision_at_k",
    "reciprocal_rank_at_k",
    "average_precision_at_k",
    "dcg_at_k",
    "ndcg_at_k",
    "macro_average",
    "summarize_by_key",
]

#: 报告默认输出的截断位置
DEFAULT_KS: Tuple[int, ...] = (1, 3, 5, 10)


def _dedupe_preserving_order(ids: Iterable[str]) -> List[str]:
    """去重并保留首次出现的顺序（等价于「同名次只计最高名次」）"""
    seen: set[str] = set()
    unique: List[str] = []
    for item in ids:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def _validate_k(k: int) -> None:
    if not isinstance(k, int) or isinstance(k, bool):
        raise TypeError(f"k must be an int, got {type(k).__name__}")
    if k < 1:
        raise ValueError(f"k must be >= 1, got {k}")


def _validate_answers(relevant: Iterable[str]) -> List[str]:
    """校验并规范化标准答案集合。

    空集合代表「无标准答案」，指标无定义——显式抛错而非返回常量，
    避免调用方把「无标注」误当成「零命中」混入宏观平均。
    """
    normalized = [str(item) for item in relevant]
    if not normalized:
        raise ValueError("relevant must be non-empty; metrics are undefined without ground truth")
    return normalized


def _top_k(retrieved: Sequence[str], k: int) -> List[str]:
    _validate_k(k)
    return _dedupe_preserving_order(retrieved)[:k]


def recall_at_k(retrieved: Sequence[str], relevant: Sequence[str], k: int) -> float:
    """Recall@k = |R ∩ T_k| / |R|

    分母为完整相关集 ``|R|``，因此 Recall@k 随 k 单调不减。
    衡量的是**召回上限**：即使排序很差，只要相关项进入了前 k 就能得分。
    """
    answer = _validate_answers(relevant)
    hits = len(set(_top_k(retrieved, k)) & set(answer))
    return hits / len(answer)


def hit_at_k(retrieved: Sequence[str], relevant: Sequence[str], k: int) -> float:
    """Hit@k = 1[|R ∩ T_k| > 0]，返回 1.0 或 0.0

    分母与召回率无关，适合观察「是否存在可用答案」，对噪声不敏感。
    """
    answer = _validate_answers(relevant)
    return 1.0 if set(_top_k(retrieved, k)) & set(answer) else 0.0


def precision_at_k(retrieved: Sequence[str], relevant: Sequence[str], k: int) -> float:
    """Precision@k = |R ∩ T_k| / k

    分母固定为 k（而非实际返回条数），便于跨查询横向比较；
    该指标衡量噪声比例，随 k 增大通常下降。
    """
    answer = _validate_answers(relevant)
    hits = len(set(_top_k(retrieved, k)) & set(answer))
    return hits / k


def reciprocal_rank_at_k(retrieved: Sequence[str], relevant: Sequence[str], k: int) -> float:
    """RR@k = 1 / rank_first_relevant，未命中记 0

    单查询结果；宏观平均后即为 MRR@k。只关心「第一条相关结果排多前」。
    """
    answer = set(_validate_answers(relevant))
    for rank, doc_id in enumerate(_top_k(retrieved, k), start=1):
        if doc_id in answer:
            return 1.0 / rank
    return 0.0


def average_precision_at_k(retrieved: Sequence[str], relevant: Sequence[str], k: int) -> float:
    """AP@k = (1 / |R|) · Σ_{i=1..k} P@i · rel(i)

    分母使用完整相关集 ``|R|``，故未召回的相关项以 0 计入，等同于惩罚；
    宏观平均后即为 MAP@k。
    """
    answer = set(_validate_answers(relevant))
    top = _top_k(retrieved, k)
    running_hits = 0
    score = 0.0
    for rank, doc_id in enumerate(top, start=1):
        if doc_id in answer:
            running_hits += 1
            score += running_hits / rank
    return score / len(answer)


def dcg_at_k(retrieved: Sequence[str], gains: Mapping[str, float], k: int) -> float:
    """DCG@k = Σ (2^gain − 1) / log2(rank + 1)

    ``gains`` 为分级相关度映射（如 2=高度相关 / 1=部分相关 / 0=不相关）。
    未出现在 ``gains`` 中的 ID 视为增益 0。
    """
    _validate_k(k)
    total = 0.0
    for rank, doc_id in enumerate(_dedupe_preserving_order(retrieved)[:k], start=1):
        gain = float(gains.get(doc_id, 0.0))
        if gain <= 0:
            continue
        total += (2.0**gain - 1.0) / log2(rank + 1)
    return total


def ndcg_at_k(retrieved: Sequence[str], gains: Mapping[str, float], k: int) -> float:
    """nDCG@k = DCG@k / IDCG@k

    IDCG 由**完整相关集的理想排序**（增益降序）截断到 k 计算，因此
    ``|R| < k`` 时不会因为「填不满 k 个位置」而被扣分。
    二值相关性场景下等价于使用增益 ``rel ∈ {0, 1}``。

    Raises:
        ValueError: ``gains`` 中不存在任何正增益（无标准答案，指标无定义）。
    """
    _validate_k(k)
    positive = {doc_id: float(g) for doc_id, g in gains.items() if float(g) > 0}
    if not positive:
        raise ValueError("gains must contain at least one positive gain; nDCG is undefined")

    ideal = sorted(_dedupe_preserving_order(gains.keys()), key=lambda d: -positive.get(d, 0.0))
    ideal_dcg = dcg_at_k(ideal, positive, k)
    if ideal_dcg <= 0.0:
        raise ValueError("ideal DCG is zero; nDCG is undefined")
    return dcg_at_k(retrieved, positive, k) / ideal_dcg


def macro_average(values: Sequence[Optional[float]]) -> Optional[float]:
    """宏观平均（单查询指标等权）。

    跳过 ``None``（指标无定义的查询）。若全部为 ``None`` 则返回 ``None``，
    由调用方决定如何呈现，而不是伪造一个 0.0。
    """
    valid = [v for v in values if v is not None]
    if not valid:
        return None
    return sum(valid) / len(valid)


def summarize_by_key(
    per_query: Mapping[str, Optional[float]],
    groups: Mapping[str, str],
) -> Dict[str, Optional[float]]:
    """按分组键聚合单查询指标，返回 ``{group: macro_average}``

    Args:
        per_query: ``{query_id: metric_value}``
        groups: ``{query_id: group_name}``（如查询类型：fact / exact_term / …）
    """
    buckets: Dict[str, List[Optional[float]]] = {}
    for query_id, value in per_query.items():
        group = groups.get(query_id, "unknown")
        buckets.setdefault(group, []).append(value)
    return {group: macro_average(values) for group, values in sorted(buckets.items())}
