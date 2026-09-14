"""RAG 检索质量评测层（与业务代码解耦，可离线运行）

模块划分：

* :mod:`app.rag_eval.metrics`   —— 纯函数指标（Recall / MRR / nDCG / MAP / Hit）
* :mod:`app.rag_eval.dataset`   —— 金标准集与语料的 schema、加载、校验
* :mod:`app.rag_eval.retrievers`—— 离线确定性 / 端到端 Qdrant / 重排装饰器
* :mod:`app.rag_eval.runner`    —— 编排与聚合
* :mod:`app.rag_eval.report`    —— JSON + Markdown 报告与回归门禁

使用入口见 ``backend/scripts/rag_eval.py``。

**为何独立成层**：评测代码一旦与业务代码混写，就会为了「跑通」而放宽口径，
最终指标反映的是评测脚本的宽容度而非检索质量。本层只依赖
``app.core.vector_db.search_points`` 这一处业务实现，用以保证评测口径与线上一致。
"""

from app.rag_eval.dataset import CorpusEntry, GoldenQuery, GoldenSet
from app.rag_eval.index_manifest import IndexManifest, load_index_manifest
from app.rag_eval.metrics import (
    average_precision_at_k,
    dcg_at_k,
    hit_at_k,
    macro_average,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank_at_k,
)
from app.rag_eval.report import (
    RegressionCheck,
    check_regression,
    load_baseline,
    render_comparison_markdown,
    render_markdown,
    write_json,
    write_markdown,
)
from app.rag_eval.retrievers import (
    InMemoryRetriever,
    PassageMappedRetriever,
    QdrantRetriever,
    RerankedRetriever,
    RetrievalResult,
    Retriever,
)
from app.rag_eval.runner import EvalRun, Evaluator, QueryOutcome, merge_runs

__all__ = [
    # metrics
    "average_precision_at_k",
    "dcg_at_k",
    "hit_at_k",
    "macro_average",
    "ndcg_at_k",
    "precision_at_k",
    "recall_at_k",
    "reciprocal_rank_at_k",
    # dataset
    "CorpusEntry",
    "GoldenQuery",
    "GoldenSet",
    # index manifest
    "IndexManifest",
    "load_index_manifest",
    # retrievers
    "InMemoryRetriever",
    "PassageMappedRetriever",
    "QdrantRetriever",
    "RerankedRetriever",
    "RetrievalResult",
    "Retriever",
    # runner
    "EvalRun",
    "Evaluator",
    "QueryOutcome",
    "merge_runs",
    # report
    "RegressionCheck",
    "check_regression",
    "load_baseline",
    "render_comparison_markdown",
    "render_markdown",
    "write_json",
    "write_markdown",
]
