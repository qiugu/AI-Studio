import logging

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, HnswConfigDiff, VectorParams

from app.core.config import config

logger = logging.getLogger(__name__)

_qdrant_client: QdrantClient | None = None


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


def get_vector_size_for_model(model_name: str) -> int:
    """根据 embedding 模型名称返回向量维度"""
    if not model_name or not model_name.strip():
        raise ValueError("Embedding model name cannot be empty")

    model_name = model_name.strip().lower()
    model_dimensions = {
        "BAAI/bge-m3": 1024,
        "BAAI/bge-large-zh-v1.5": 1024
    }

    if model_name in model_dimensions:
        return model_dimensions[model_name]

    if model_name.startswith("baai/bge-") or model_name.startswith("bge-"):
        return 1024

    raise ValueError(f"Unsupported embedding model for vector size lookup: {model_name}")


def get_or_create_collection(kb_id: int, vector_size: int = 1024) -> str:
    """确保知识库对应的 Collection 存在，返回 collection_name"""
    collection_name = f"kb_{kb_id}"
    client = get_qdrant_client()
    existing = {c.name for c in client.get_collections().collections}
    if collection_name not in existing:
        client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
            hnsw_config=HnswConfigDiff(m=16, ef_construct=100),
        )
        logger.info("Created Qdrant collection: %s", collection_name)
    return collection_name


def delete_tenant_vectors(tenant_id: int) -> None:
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
