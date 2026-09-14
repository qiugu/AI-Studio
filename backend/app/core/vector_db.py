import logging
from dataclasses import dataclass
from typing import Any, List, Optional, Sequence

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, HnswConfigDiff, VectorParams

from app.core.config import config

logger = logging.getLogger(__name__)

_qdrant_client: QdrantClient | None = None


@dataclass(frozen=True)
class RetrievedPoint:
    """单条向量召回结果（仅含排序所需信息）"""

    id: str
    score: float


def get_qdrant_client() -> QdrantClient:
    global _qdrant_client
    if _qdrant_client is None:
        _qdrant_client = QdrantClient(
            url=config.qdrant_url,
            api_key=config.qdrant_api_key or None,
            timeout=3600,
            check_compatibility=False
        )
    return _qdrant_client


def init_vector_db() -> None:
    """应用启动时验证 Qdrant 连通性"""
    try:
        client = get_qdrant_client()
        client.get_collections()
        logger.info("Qdrant connection verified")
    except Exception as e:
        logger.warning("Could not connect to Qdrant: %s", e)


def search_points(
    collection_name: str,
    query_vector: Sequence[float],
    limit: int,
    score_threshold: Optional[float] = None,
    query_filter: Optional[Any] = None,
    client: Optional[QdrantClient] = None,
) -> List[RetrievedPoint]:
    """稠密向量召回的**唯一实现入口**。

    业务检索（`KnowledgeBaseService.search`）与离线评测（`rag_eval.QdrantRetriever`）
    必须共用本函数，任何一侧单独改动都会导致评测口径与线上口径分叉——
    评测结论将不再适用于线上，这是评测体系最容易失效的地方。

    本函数不吞异常：Qdrant 不可用时向上抛出，由调用方决定降级策略
    （业务侧返回空结果并记录日志，评测侧应中断并报错，避免产出失真的指标）。

    Args:
        collection_name: 形如 ``kb_{kb_id}``
        query_vector: 查询向量，长度须与 collection 维度一致
        limit: 召回条数
        score_threshold: 相似度下限，``None`` 表示不启用阈值过滤
        query_filter: 可选的 Qdrant Filter（如按 tenant_id / doc_id 限定范围）
        client: 可注入的 Qdrant 客户端，便于测试

    Returns:
        按相似度降序排列的 :class:`RetrievedPoint` 列表

    Note:
        使用 ``query_points`` 而非已废弃的 ``search``（D8）；两者在纯稠密召回下
        语义等价，已实测比对 top-10 排序一致。``query_points`` 同时是 Phase 5
        混合检索 prefetch + RRF 所需的 API 形态。
    """
    if limit <= 0:
        raise ValueError("limit must be a positive integer")

    qdrant = client or get_qdrant_client()
    response = qdrant.query_points(
        collection_name=collection_name,
        query=list(query_vector),
        limit=limit,
        score_threshold=score_threshold,
        query_filter=query_filter,
        with_payload=False,
        with_vectors=False,
    )
    return [RetrievedPoint(id=str(point.id), score=float(point.score)) for point in response.points]


def get_vector_size_for_model(model_name: str) -> int:
    """根据 embedding 模型名称返回向量维度"""
    if not model_name or not model_name.strip():
        raise ValueError("Embedding model name cannot be empty")

    model_name = model_name.strip().lower()
    model_dimensions = {
        "BAAI/bge-m3": 1024,
        "BAAI/bge-large-zh-v1.5": 1024,
        "BAAI/bge-base-zh-v1.5": 768,
        "BAAI/bge-small-zh-v1.5": 512,
        "shibing624/text2vec-base-chinese": 768,
        # OpenAI / Azure OpenAI：embedding_provider 支持这两类供应商，
        # 缺少映射会导致创建知识库时维度推导失败并返回 500。
        "text-embedding-3-small": 1536,
        "text-embedding-3-large": 3072,
        "text-embedding-ada-002": 1536,
    }

    if model_name in model_dimensions:
        return model_dimensions[model_name]

    # 家族兜底：未知具体版本时按系列推断维度
    if model_name.startswith("baai/bge-large") or model_name.startswith("bge-large"):
        return 1024
    if model_name.startswith("baai/bge-base") or model_name.startswith("bge-base"):
        return 768
    if model_name.startswith("baai/bge-small") or model_name.startswith("bge-small"):
        return 512
    if model_name.startswith("baai/bge-m3") or model_name.startswith("bge-m3"):
        return 1024
    if "text2vec" in model_name:
        return 768
    # OpenAI 系列可能带部署后缀（如 Azure 的 -zh 变体），按前缀匹配
    if model_name.startswith("text-embedding-3-small"):
        return 1536
    if model_name.startswith("text-embedding-3-large"):
        return 3072
    if model_name.startswith("text-embedding-ada-002"):
        return 1536

    raise ValueError(f"Unsupported embedding model for vector size lookup: {model_name}")


def get_or_create_collection(kb_id: str, vector_size: int = 1024) -> str:
    """确保知识库对应的 Collection 存在，返回 collection_name。

    并发处理同一知识库的多个文档时，两个任务可能同时尝试建表，
    后者会收到 409 Conflict；此处将其视为“集合已存在”正常忽略。
    若集合已存在但维度不一致（模型被更换），则抛出明确错误。
    """
    from qdrant_client.http.exceptions import UnexpectedResponse

    collection_name = f"kb_{kb_id}"
    client = get_qdrant_client()
    existing = {c.name for c in client.get_collections().collections}
    if collection_name not in existing:
        try:
            client.create_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
                hnsw_config=HnswConfigDiff(m=16, ef_construct=100),
            )
            logger.info("Created Qdrant collection: %s", collection_name)
        except UnexpectedResponse as exc:
            # 409 Conflict：并发创建同一集合，视为已存在即可
            if getattr(exc, "status_code", None) == 409 or "Conflict" in str(exc):
                logger.info("Collection %s already exists (concurrent create), skip", collection_name)
            else:
                raise
    else:
        # 集合已存在，校验向量维度与当前模型一致
        actual = client.get_collection(collection_name).config.params.vectors.size
        if actual != vector_size:
            raise ValueError(
                f"Collection {collection_name} exists with vector_size={actual}, "
                f"but {vector_size} requested (embedding model mismatch)"
            )
    return collection_name


def delete_tenant_vectors(tenant_id: str) -> None:
    """删除指定租户的所有向量数据（租户注销时调用）"""
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    client = get_qdrant_client()
    collections = [c.name for c in client.get_collections().collections]
    for collection_name in collections:
        try:
            client.delete(
                collection_name=collection_name,
                points_selector=Filter(
                    must=[FieldCondition(key="tenant_id", match=MatchValue(value=tenant_id))]
                ),
            )
        except Exception as e:
            logger.warning("Failed to delete vectors for tenant %s in %s: %s", tenant_id, collection_name, e)
