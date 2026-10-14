import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    HnswConfigDiff,
    SparseVector,
    SparseVectorParams,
    VectorParams,
)

from app.core.config import config

logger = logging.getLogger(__name__)

_qdrant_client: QdrantClient | None = None

#: 混合检索集合布局中的命名向量。稠密叫 ``dense``、稀疏叫 ``text``。
#: 之所以要「命名」，是因为 Qdrant **不支持向已存在的匿名稠密集合原地追加稀疏向量**
#: （实测报 ``Not existing vector name error``）。因此开启混合检索必须新建/回填集合，
#: 不能复用既有匿名布局的集合。
NAMED_DENSE_VECTOR = "dense"
NAMED_SPARSE_VECTOR = "text"

#: 集合布局探测结果的缓存时长（秒）。
#: 每次检索都调 ``get_collection`` 会平白增加一次元数据往返；但完全不缓存又会让
#: 「刚回填完就生效」变得不可能。60 秒是「免掉绝大部分往返」与「回填后一分钟内生效」
#: 之间的折中。
_LAYOUT_CACHE_TTL_SECONDS = 60.0
#: ``{collection_name: (monotonic_ts, has_sparse)}``
_layout_cache: Dict[str, Tuple[float, bool]] = {}


def reset_layout_cache() -> None:
    """清空集合布局缓存（测试与「回填后立即生效」场景需要）"""
    _layout_cache.clear()


def collection_name_for(kb_id: str, active: Optional[str] = None) -> str:
    """知识库 id → Qdrant 集合名

    集合命名规则的**唯一来源**。调用方若各自拼 ``f"kb_{kb_id}"``，一旦规则调整
    就会出现「写进 A 集合、从 B 集合查」的静默故障，且不会有任何报错。

    ``active`` 是知识库的**灰度 / 回滚指针**（``knowledge_bases.active_collection``）：

    * 非空 → 直接采用它（重建后的新集合），写入与检索都走新集合；
    * 为空 → 退回 ``kb_{kb_id}``，行为与引入该指针之前**完全一致**。

    指针作为**覆盖值**在此解析，而不是各调用方自己判断，是为了让「当前生效集合」
    只有一个真值来源——否则「写入进了新集合、检索还在查旧集合」这类故障不会有
    任何报错，只会表现为「刚上传的文档搜不到」。
    """
    return active or f"kb_{kb_id}"


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
    using: Optional[str] = None,
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
        using: 命名向量名。**默认 ``None``，此时不传 ``using``，行为与改造前逐位一致**
            （匿名稠密集合必须走这条路径）。混合布局的集合传
            :data:`NAMED_DENSE_VECTOR`。

    Returns:
        按相似度降序排列的 :class:`RetrievedPoint` 列表

    Note:
        使用 ``query_points`` 而非已废弃的 ``search``（D8）；两者在纯稠密召回下
        语义等价，已实测比对 top-10 排序一致。
    """
    if limit <= 0:
        raise ValueError("limit must be a positive integer")

    qdrant = client or get_qdrant_client()
    kwargs: Dict[str, Any] = {}
    if using is not None:
        kwargs["using"] = using
    response = qdrant.query_points(
        collection_name=collection_name,
        query=list(query_vector),
        limit=limit,
        score_threshold=score_threshold,
        query_filter=query_filter,
        with_payload=False,
        with_vectors=False,
        **kwargs,
    )
    return [RetrievedPoint(id=str(point.id), score=float(point.score)) for point in response.points]


def search_sparse_points(
    collection_name: str,
    indices: Sequence[int],
    values: Sequence[float],
    limit: int,
    query_filter: Optional[Any] = None,
    client: Optional[QdrantClient] = None,
    using: str = NAMED_SPARSE_VECTOR,
) -> List[RetrievedPoint]:
    """稀疏（词法）向量召回的**唯一实现入口**

    与 :func:`search_points` 同构，供线上检索与离线评测共用，避免两处各写一份
    稀疏查询而产生口径分叉。

    Args:
        collection_name: 形如 ``kb_{kb_id}``，须为混合布局（含命名稀疏向量）
        indices: 稀疏下标（``uint32``），来自 :class:`app.utils.sparse.SparseEncoder`
        values: 与 ``indices`` 等长的权重
        limit: 召回条数
        query_filter: 可选 Qdrant Filter
        client: 可注入客户端（测试用）
        using: 稀疏向量名，默认 :data:`NAMED_SPARSE_VECTOR`

    Returns:
        按 BM25 分数降序的 :class:`RetrievedPoint` 列表

    Note:
        **不设 ``score_threshold``**：BM25 分数无界（取决于语料与查询词数），
        任何绝对阈值都不可跨库迁移。相对筛选交给融合后的截断完成。
        空 ``indices`` 直接返回空列表——Qdrant 会拒绝空稀疏向量，
        而「查询没有任何可匹配词元」是完全正常的输入（如纯标点查询）。
    """
    if limit <= 0:
        raise ValueError("limit must be a positive integer")
    if not indices:
        return []
    if len(indices) != len(values):
        raise ValueError(
            f"sparse indices/values length mismatch: {len(indices)} != {len(values)}"
        )

    qdrant = client or get_qdrant_client()
    response = qdrant.query_points(
        collection_name=collection_name,
        query=SparseVector(
            indices=[int(i) for i in indices],
            values=[float(v) for v in values],
        ),
        using=using,
        limit=limit,
        query_filter=query_filter,
        with_payload=False,
        with_vectors=False,
    )
    return [RetrievedPoint(id=str(point.id), score=float(point.score)) for point in response.points]


def hybrid_point_vector(
    dense: Sequence[float],
    sparse_indices: Sequence[int],
    sparse_values: Sequence[float],
) -> Dict[str, Any]:
    """构造混合布局的 point 向量字段（命名稠密 + 命名稀疏）

    集中在此处是为了让「向量名」只有一个来源：入库侧与检索侧若各自硬编码
    ``"dense"`` / ``"text"``，一旦改名就会出现「写进去但查不到」的静默故障。
    """
    vector: Dict[str, Any] = {NAMED_DENSE_VECTOR: list(dense)}
    if sparse_indices:
        vector[NAMED_SPARSE_VECTOR] = SparseVector(
            indices=[int(i) for i in sparse_indices],
            values=[float(v) for v in sparse_values],
        )
    return vector


def create_hybrid_collection(
    collection_name: str,
    vector_size: int,
    *,
    recreate: bool = False,
    client: Optional[QdrantClient] = None,
) -> bool:
    """按「命名稠密 + 命名稀疏」布局创建集合，返回是否实际创建

    与 :func:`get_or_create_collection` 的区别：本函数接受**显式集合名**，用于回填
    脚本把旧集合的内容写入一个**新名字**的集合（例如 ``kb_x`` → ``kb_x_hybrid``），
    以便切读失败时能立刻退回旧集合。按 ``kb_id`` 推导名字的入口不支持这一点。

    Args:
        recreate: ``True`` 时若目标已存在则先删除。**回填脚本默认要求目标不存在**，
            避免把半成品集合当成成品继续写；只有显式重跑时才用 ``recreate``。
    """
    qdrant = client or get_qdrant_client()
    existing = {c.name for c in qdrant.get_collections().collections}
    if collection_name in existing:
        if not recreate:
            return False
        qdrant.delete_collection(collection_name=collection_name)

    qdrant.create_collection(
        collection_name=collection_name,
        vectors_config={NAMED_DENSE_VECTOR: VectorParams(size=vector_size, distance=Distance.COSINE)},
        sparse_vectors_config={NAMED_SPARSE_VECTOR: SparseVectorParams()},
        hnsw_config=HnswConfigDiff(m=16, ef_construct=100),
    )
    _layout_cache.pop(collection_name, None)
    logger.info("Created hybrid collection: %s", collection_name)
    return True


def collection_layout(
    collection_name: str,
    client: Optional[QdrantClient] = None,
) -> str:
    """探测集合布局，返回 ``"missing"`` / ``"legacy_dense"`` / ``"hybrid"`` 之一

    为什么需要这一探测：``retrieval_hybrid_enabled`` 是进程级开关，而集合布局是
    **逐库的**（且要求回填）。若对未回填的库直接发稀疏查询，Qdrant 会抛
    ``Not existing vector name error``，把一次本可用的检索变成失败。显式探测让
    「开关已开但该库未回填」退化为**只用稠密分支**，而不是报错；入库侧同理，
    可继续以稠密写入而不中断上传。

    「缺失」与「旧布局」必须区分开：缺失时应当**创建**目标布局，而旧布局只能
    回填。把两者混为 ``has_sparse=False`` 会导致「新建库意外沿用旧布局」。

    结果带 60 秒缓存（见 :data:`_LAYOUT_CACHE_TTL_SECONDS`）：既避免每次检索都多一次
    元数据往返，又保证回填完成后一分钟内自动生效。
    """
    now = time.monotonic()
    cached = _layout_cache.get(collection_name)
    if cached is not None and now - cached[0] < _LAYOUT_CACHE_TTL_SECONDS:
        return cached[1]

    qdrant = client or get_qdrant_client()
    try:
        info = qdrant.get_collection(collection_name)
    except Exception:  # noqa: BLE001 - 探测本身不应抛错：缺失/不可达都按「不适用」处理
        # **刻意不缓存**：此分支无法区分「集合确实不存在」与「探测本身瞬时失败」。
        # 若把结果缓存 60 秒，一次瞬时故障会让混合布局的集合在这 60 秒内被当成
        # 旧布局，进而发出匿名向量查询并持续收到 400——把一次抖动放大成一分钟的
        # 持续故障。不缓存则下一次查询自然自愈。代价是集合真不存在时会在错误路径上
        # 重复探测，而该路径本就以检索失败告终，不值一提。
        return "missing"
    else:
        sparse_config = getattr(info.config.params, "sparse_vectors", None) or {}
        layout = "hybrid" if NAMED_SPARSE_VECTOR in sparse_config else "legacy_dense"

    _layout_cache[collection_name] = (now, layout)
    return layout


def supports_sparse_vectors(
    collection_name: str,
    client: Optional[QdrantClient] = None,
) -> bool:
    """集合是否已完成混合布局（存在命名稀疏向量）"""
    return collection_layout(collection_name, client=client) == "hybrid"


def collection_exists(
    collection_name: str,
    client: Optional[QdrantClient] = None,
) -> bool:
    """集合是否存在（**不带缓存**）

    与 :func:`collection_layout` 的关键差别是**不读也不写布局缓存**。清理类操作
    （删文档、删知识库、GC）必须以库内实况为准：缓存里一个过期的「不存在」会让
    本该执行的删除被静默跳过，留下孤儿向量——而这类残留只在事后对账时才会暴露。
    代价是多一次元数据往返，清理路径本就低频，可以接受。
    """
    qdrant = client or get_qdrant_client()
    try:
        return collection_name in {
            c.name for c in qdrant.get_collections().collections
        }
    except Exception:  # noqa: BLE001 - 探测失败按「不存在」处理：宁可不删也不误删
        logger.warning("Failed to list Qdrant collections", exc_info=True)
        return False


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


def _existing_dense_size(info: Any) -> Optional[int]:
    """从集合信息中取出稠密向量维度；命名布局与匿名布局都要兼容"""
    vectors = getattr(info.config.params, "vectors", None)
    if isinstance(vectors, dict):
        dense = vectors.get(NAMED_DENSE_VECTOR)
        return getattr(dense, "size", None)
    return getattr(vectors, "size", None)


def get_or_create_collection(
    kb_id: str,
    vector_size: int = 1024,
    *,
    hybrid: bool = False,
    active: Optional[str] = None,
) -> str:
    """确保知识库对应的 Collection 存在，返回 collection_name。

    Args:
        hybrid: ``True`` 时创建**命名稠密 + 命名稀疏**布局（混合检索所需）。
            注意：**已存在的匿名稠密集合无法原地升级**——Qdrant 拒绝向匿名集合
            追加稀疏向量（实测 ``Not existing vector name error``）。此情况下本函数
            抛 ``ValueError`` 并指向回填脚本，而不是静默返回一个「看起来能建、
            实际查不到稀疏」的集合。既有布局请求（``hybrid=False``）行为与改造前
            逐位一致。
        active: 知识库的灰度 / 回滚指针（``knowledge_bases.active_collection``）。
            非空时在该集合上建/取，为空时用 ``kb_{kb_id}``。**必须由调用方传入**：
            若建集合时忽略指针、检索时又读指针，就会出现「写进 A、查 B」的静默错配。

    并发处理同一知识库的多个文档时，两个任务可能同时尝试建表，
    后者会收到 409 Conflict；此处将其视为“集合已存在”正常忽略。
    若集合已存在但维度不一致（模型被更换），则抛出明确错误。
    """
    from qdrant_client.http.exceptions import UnexpectedResponse

    collection_name = collection_name_for(kb_id, active)
    client = get_qdrant_client()
    existing = {c.name for c in client.get_collections().collections}
    if collection_name not in existing:
        try:
            if hybrid:
                client.create_collection(
                    collection_name=collection_name,
                    vectors_config={
                        NAMED_DENSE_VECTOR: VectorParams(
                            size=vector_size, distance=Distance.COSINE
                        )
                    },
                    sparse_vectors_config={NAMED_SPARSE_VECTOR: SparseVectorParams()},
                    hnsw_config=HnswConfigDiff(m=16, ef_construct=100),
                )
            else:
                client.create_collection(
                    collection_name=collection_name,
                    vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
                    hnsw_config=HnswConfigDiff(m=16, ef_construct=100),
                )
            logger.info(
                "Created Qdrant collection: %s (hybrid=%s)", collection_name, hybrid
            )
        except UnexpectedResponse as exc:
            # 409 Conflict：并发创建同一集合，视为已存在即可
            if getattr(exc, "status_code", None) == 409 or "Conflict" in str(exc):
                logger.info("Collection %s already exists (concurrent create), skip", collection_name)
            else:
                raise
    else:
        # 集合已存在，校验向量维度与当前模型一致
        info = client.get_collection(collection_name)
        actual = _existing_dense_size(info)
        if actual is not None and actual != vector_size:
            raise ValueError(
                f"Collection {collection_name} exists with vector_size={actual}, "
                f"but {vector_size} requested (embedding model mismatch)"
            )
        if hybrid and not supports_sparse_vectors(collection_name, client=client):
            raise ValueError(
                f"Collection {collection_name} uses the legacy anonymous-dense layout and "
                f"cannot be upgraded in place: Qdrant rejects adding a sparse vector to an "
                f"existing unnamed-vector collection. Rebuild it with "
                f"scripts/backfill_hybrid_collection.py instead."
            )
    return collection_name


def delete_collection(kb_id: str, *, active: Optional[str] = None) -> bool:
    """删除知识库相关的 Qdrant 集合，返回是否实际发生了删除

    为什么删除知识库时必须调用它：集合不随知识库的软删消失，会永久残留并占用
    存储与内存索引。集合名由 ``kb_{kb_id}`` 派生，故此处只需 kb_id，避免调用方
    各自拼接名字而产生不一致。

    引入灰度指针后「该知识库的集合」可能是两个：重建后的新集合（``active`` 指针
    所指）与重建前的旧集合。删除知识库时**两个都要删**——旧集合被保留的理由只是
    「支持回滚」，而知识库已删之后不存在可回滚的对象，留着只会永久占用存储。

    不吞异常：调用方自行决定是否降级——删除知识库时集合删除失败只影响存储回收，
    不影响「知识库已删」这一业务事实，因此调用方记录告警即可。
    """
    names = {collection_name_for(kb_id)}
    if active:
        names.add(active)

    client = get_qdrant_client()
    existing = {c.name for c in client.get_collections().collections}
    removed = False
    for collection_name in sorted(names):
        if collection_name not in existing:
            continue
        client.delete_collection(collection_name=collection_name)
        logger.info("Deleted Qdrant collection: %s", collection_name)
        removed = True
    return removed


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
