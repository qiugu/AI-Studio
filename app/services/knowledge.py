"""知识库服务"""
import logging
import math
import os
import shutil
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, List, Dict, Any
from datetime import datetime

from qdrant_client.models import PointIdsList
from sqlalchemy.orm import Session

from app.models.knowledge_base import KnowledgeBase
from app.models.knowledge_document import KnowledgeDocument, DocumentStatus
from app.models.knowledge_chunk import KnowledgeChunk
from app.repositories.knowledge import (
    KnowledgeBaseRepository,
    KnowledgeDocumentRepository,
    KnowledgeChunkRepository,
)
from app.core.config import config
from app.core.exceptions import NotFoundException, ValidationException
from app.core.vector_db import (
    NAMED_DENSE_VECTOR,
    RetrievedPoint,
    collection_exists,
    collection_layout,
    collection_name_for,
    delete_collection,
    get_or_create_collection,
    get_qdrant_client,
    get_vector_size_for_model,
    search_points,
    search_sparse_points,
)
from app.services.knowledge_processor import process_document_task
from app.utils.embedding import get_embedding_client
from app.utils.reranker import RerankerUnavailable, get_reranker
from app.utils.retrieval_fusion import weighted_fuse
from app.utils.retrieval_context import (
    build_context_header,
    collect_window_indexes,
    iter_unique,
    join_window,
)
from app.utils.sparse import default_encoder

logger = logging.getLogger(__name__)

#: 检索降级原因。用常量而非自由文本，避免调用方去解析字符串。
DEGRADED_COLLECTION_NOT_FOUND = "collection_not_found"
DEGRADED_BACKEND_UNAVAILABLE = "backend_unavailable"


@dataclass
class SearchOutcome:
    """检索结果 + 诊断信息

    为什么需要它：``search()`` 在 Qdrant 异常时返回空列表，使「后端故障」与
    「确无相关内容」在调用侧完全不可区分。本项目曾因此在首轮勘察中把「集合不存在」
    误读为「库里没有向量」，得出与事实完全相反的结论。

    为什么不让 ``search()`` 直接返回本结构：它的 list 返回契约已被前端
    （``SearchResult[]``）与 Agent 工具依赖，改成对象属破坏性变更。因此新增
    ``search_with_diagnostics()`` 承载诊断，``search()`` 委托它并只返回结果列表。
    """

    results: List[Dict[str, Any]]
    degraded: bool = False
    reason: Optional[str] = None
    collection: Optional[str] = None


def _classify_qdrant_failure(exc: Exception) -> str:
    """把 Qdrant 异常归因为「集合缺失」或「后端不可用」

    两类故障的处理方式不同，日志级别也应不同：集合缺失属**配置 / 数据故障**，
    不会自愈，必须显式暴露（``error``）；后端不可用多为瞬时问题，按 ``warning``
    记录并依赖既有告警链路。若不区分，日志里就只剩一句「检索失败」，定位只能靠猜。
    """
    status = getattr(exc, "status_code", None)
    text = str(exc).lower()
    missing_markers = ("not found", "doesn't exist", "does not exist", "not exist")
    if status == 404 or any(marker in text for marker in missing_markers):
        return DEGRADED_COLLECTION_NOT_FOUND
    return DEGRADED_BACKEND_UNAVAILABLE


def _sigmoid(value: float) -> float:
    """把精排 logit 压缩到 (0, 1)，使展示分数与返回顺序保持单调一致

    CrossEncoder 输出的是未归一化 logit（可为负、可远大于 1）。若直接把它当作
    ``score`` 返回，调用方按分数展示/过滤时会与精排顺序产生矛盾——例如排在第一的
    结果分数是负数。压缩后分数仍**只有相对含义**（不是概率），这一点在文档中已说明。
    """
    if value >= 0:
        return 1.0 / (1.0 + math.exp(-value))
    exp_value = math.exp(value)
    return exp_value / (1.0 + exp_value)


class KnowledgeBaseService:
    """知识库服务"""

    def __init__(self, db: Session, tenant_id: str):
        self.db = db
        self.tenant_id = tenant_id
        self.kb_repo = KnowledgeBaseRepository(db=db, tenant_id=tenant_id)
        self.doc_repo = KnowledgeDocumentRepository(db=db, tenant_id=tenant_id)
        self.chunk_repo = KnowledgeChunkRepository(db=db, tenant_id=tenant_id)

    # ── 知识库 CRUD ──────────────────────────────────────────────────────────

    def create_knowledge_base(
        self,
        name: str,
        description: Optional[str] = None,
        embedding_model: Optional[str] = None,
    ) -> KnowledgeBase:
        """创建知识库

        embedding_model 缺省时取服务端配置：避免 API 层默认值与维度映射表
        （get_vector_size_for_model）各写一套，导致建库时维度推导失败。
        """
        if not name or not name.strip():
            raise ValidationException("Knowledge base name cannot be empty")

        embedding_model = embedding_model or config.embedding_model

        kb = self.kb_repo.create(
            name=name.strip(),
            description=description,
            embedding_model=embedding_model,
        )

        # 创建对应的 Qdrant Collection
        vector_size = get_vector_size_for_model(embedding_model)
        get_or_create_collection(kb_id=kb.id, vector_size=vector_size)

        self.db.commit()
        return kb

    def get_knowledge_base(self, kb_id: str) -> KnowledgeBase:
        """获取知识库详情"""
        kb = self.kb_repo.get_by_id(kb_id)
        if not kb:
            raise NotFoundException("KnowledgeBase", kb_id)
        return kb

    def list_knowledge_bases(self, page: int = 1, page_size: int = 20) -> tuple[List[KnowledgeBase], int]:
        """列出知识库"""
        kbs = self.kb_repo.list(page=page, page_size=page_size)
        total = self.kb_repo.count()
        return kbs, total

    def update_knowledge_base(
        self,
        kb_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> KnowledgeBase:
        """更新知识库"""
        kb = self.get_knowledge_base(kb_id)
        updates = {}
        if name is not None:
            if not name.strip():
                raise ValidationException("Knowledge base name cannot be empty")
            updates["name"] = name.strip()
        if description is not None:
            updates["description"] = description

        self.kb_repo.update(kb, **updates)
        self.db.commit()
        return kb

    def delete_knowledge_base(self, kb_id: str) -> None:
        """软删除知识库，并级联回收其文档、分块与向量

        **为什么必须在同一次操作内完成**：知识库一旦软删，其文档就不再能通过
        ``delete_document`` 清理（校验会因知识库不可见而失败，见 P2-D）。因此级联
        不是「顺手做的清理」，而是删除知识库的必要组成部分——否则会留下永久无法
        回收的孤儿文档与向量。

        向量回收采用**删除整个集合**而非逐点删除：集合名由 kb_id 派生，知识库删除后
        不会再有新点写入；而逐点删除只能覆盖「当前可见文档的分块」，会漏掉存量脏数据
        （例如历史遗留的「文档已软删、分块存活、向量在库」），这些点同样应随知识库消失。

        集合删除放在事务提交**之后**：此时「知识库已删」已是既成事实，集合删除失败
        只影响存储回收，降级为告警即可，不应把已成功的业务操作回滚掉。
        """
        kb = self.get_knowledge_base(kb_id)
        deleted_at = datetime.utcnow()

        docs = self.doc_repo.list_all_by_kb(kb_id)
        purged_chunks = 0
        for doc in docs:
            # 整个集合随后会被删除，无需逐点清理向量
            purged_chunks += self._purge_document(doc, deleted_at, delete_vectors=False)

        self.kb_repo.update(kb, deleted_at=deleted_at, document_count=0, chunk_count=0)
        self.db.commit()

        logger.info(
            "Soft-deleted knowledge base %s: %d documents, %d chunks cascaded",
            kb_id, len(docs), purged_chunks,
        )

        try:
            # 带上指针：重建之后本知识库有「新集合（指针所指）」与「旧集合」两个，
            # 知识库已删便不存在可回滚的对象，两个都必须回收。
            delete_collection(kb_id, active=kb.active_collection)
        except Exception as exc:
            logger.warning("Failed to drop Qdrant collection kb_%s: %s", kb_id, exc)

    # ── 文档管理 ──────────────────────────────────────────────────────────────

    def upload_document(
        self,
        kb_id: str,
        file_path: str,
        file_name: str,
        file_type: str,
    ) -> KnowledgeDocument:
        """
        上传文档到知识库

        Args:
            kb_id: 知识库ID
            file_path: 临时文件路径
            file_name: 原始文件名
            file_type: 文件类型（txt, pdf, docx, md）

        Returns:
            创建的文档记录
        """
        # 验证知识库存在
        kb = self.get_knowledge_base(kb_id)

        # 验证文件类型
        valid_types = ["txt", "pdf", "docx", "md"]
        if file_type.lower() not in valid_types:
            raise ValidationException(f"Unsupported file type: {file_type}")

        # 获取文件大小
        file_size = os.path.getsize(file_path)
        if file_size == 0:
            raise ValidationException("Empty file not allowed")

        # 同库重复检测：同一知识库内「同名 + 同大小」视为同一份文件的再次上传。
        # 为什么必须在写入侧拦截：每次上传都会创建新的 doc_id，而向量 id 由
        # uuid5(doc.id + index) 派生，副本之间互不覆盖，会各自在 Qdrant 中占一份
        # 向量；检索时同一段落的多个副本并列占满 top_k，这正是「检索结果一半重复」
        # 的成因。检索侧的 _dedupe_by_content 只是对存量数据的兜底，堵源头要靠这里。
        #
        # 已知局限：仅凭文件名与大小判定，无法识别「改名后重传同一份文件」；
        # 要覆盖该场景需要新增内容哈希列并配套迁移，不在本次范围内。
        duplicate = self.doc_repo.list(
            page=1, page_size=1, kb_id=kb_id, file_name=file_name, file_size=file_size
        )
        if duplicate:
            raise ValidationException(
                f"知识库中已存在同名同大小的文档「{file_name}」"
                f"（文档 ID: {duplicate[0].id}），已拒绝重复上传。"
                f"如需更新该文档，请先删除原文档后重新上传。"
            )

        # 创建文档记录并更新文档统计
        doc = self.doc_repo.create(
            kb_id=kb_id,
            file_name=file_name,
            file_type=file_type.lower(),
            file_size=file_size,
            status=DocumentStatus.PENDING,
        )
        self.kb_repo.update(kb, document_count=kb.document_count + 1)

        # 将上传文件持久化到配置目录
        dest_dir = Path(config.upload_dir) / self.tenant_id / kb_id / str(doc.id)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / Path(file_name).name
        try:
            shutil.move(file_path, dest_path)
        except Exception as exc:
            self.db.rollback()
            raise ValidationException(f"Failed to persist uploaded file: {exc}")

        doc.file_url = str(dest_path)
        self.db.commit()

        # 异步处理文档解析、分块、Embedding、存储向量
        process_document_task.delay(doc_id=doc.id, file_path=doc.file_url, tenant_id=self.tenant_id)

        return doc

    def get_document(self, doc_id: str) -> KnowledgeDocument:
        """获取文档详情"""
        doc = self.doc_repo.get_by_id(doc_id)
        if not doc:
            raise NotFoundException("KnowledgeDocument", doc_id)
        return doc

    def list_documents(
        self,
        kb_id: str,
        status: Optional[DocumentStatus] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[List[KnowledgeDocument], int]:
        """列出知识库中的文档"""
        docs = self.doc_repo.list_by_kb(kb_id=kb_id, status=status, page=page, page_size=page_size)
        total = self.doc_repo.count_by_kb(kb_id=kb_id, status=status)
        return docs, total

    def _delete_vectors(
        self,
        kb_id: str,
        point_ids: List[str],
        *,
        context: str,
        active_collection: Optional[str] = None,
    ) -> None:
        """从知识库的**所有可能集合**中删除给定向量

        为什么不是只删一个集合：引入灰度 / 回滚指针后，同一知识库的两代分块各自
        位于**不同集合**（旧代在 ``kb_{kb_id}``，新代在指针所指集合）。删除文档时
        两代分块行都会被物理删除，若只清理当前生效集合，另一集合中的向量就成了
        孤儿——其内容不会进入回答（回表查不到分块行），但会持续占用存储，并让
        「集合点数 vs 分块行数」的对账失真。

        向量清理失败**不阻断**业务主流程（数据库侧的删除才是权威状态），但必须留下
        可追溯日志——否则「删了文档却仍能检索到」会被当作检索缺陷去排查。
        """
        if not point_ids:
            return

        candidates = {collection_name_for(kb_id)}
        if active_collection:
            candidates.add(active_collection)

        try:
            qdrant = get_qdrant_client()
        except Exception as exc:  # noqa: BLE001 - 清理是尽力而为，不应阻断删除
            logger.warning("Qdrant unreachable while purging vectors (%s): %s", context, exc)
            return

        for collection_name in sorted(candidates):
            # 不带缓存的存活性判定：过期的「不存在」会让删除被静默跳过
            if not collection_exists(collection_name, client=qdrant):
                continue
            try:
                qdrant.delete(
                    collection_name=collection_name,
                    points_selector=PointIdsList(points=point_ids),
                )
            except Exception as exc:
                logger.warning(
                    "Failed to delete %d vectors from %s (%s): %s",
                    len(point_ids), collection_name, context, exc,
                )

    def _purge_document(
        self,
        doc: KnowledgeDocument,
        deleted_at: datetime,
        *,
        delete_vectors: bool = True,
        active_collection: Optional[str] = None,
    ) -> int:
        """软删除一份文档，级联**物理删除**其分块（与可选向量），返回被删除的分块数

        顺序不可调整：必须**先**取全部分块用于清理向量，**再**删除分块行。
        若先删分块，``list_by_doc_id`` 将查不到任何记录，向量清理会静默跳过，
        残留向量继续参与召回（这正是 A2 与 D9 叠加后的表现）。

        分块侧是**物理删除**——``knowledge_chunks`` 已无软删列（分块是派生数据，
        删文档后其分块再无用途，而软删行会长期占用 ``vector_id`` 唯一索引并让
        「某文档有多少分块」的统计持续失真）。「文档是否下架」的权威标记仍保留在
        ``KnowledgeDocument.deleted_at`` 上，读取侧据此过滤（P1-A）。

        不在此处 ``commit``：删除知识库需要在一个事务内回收其全部文档，逐份提交会
        产生「部分成功」的中间状态，且失败后难以判断回收到了哪一份。
        """
        self.doc_repo.update(doc, deleted_at=deleted_at)

        # 1) 先取全部分块（含两代），用于清理各自集合中的向量
        chunks = self.chunk_repo.list_by_doc_id(doc.id)
        if delete_vectors:
            self._delete_vectors(
                doc.kb_id,
                [chunk.vector_id for chunk in chunks if chunk.vector_id],
                context=f"doc={doc.id}",
                active_collection=active_collection,
            )

        # 2) 再物理删除分块行，使 vector_id 唯一索引随之释放
        return self.chunk_repo.delete_by_doc_id(doc.id)

    def delete_document(self, doc_id: str) -> None:
        """软删除文档（并级联清理分块与向量）

        D9 处置说明：软删除文档时若不同步软删除分块，检索回表的
        ``deleted_at IS NULL`` 过滤就形同虚设，已下架内容仍会被检索命中。

        **容忍知识库已被软删**：删除知识库时其文档会被一并回收，但历史数据与异常
        路径仍可能留下「库已删、文档仍在」的状态。此时若因知识库不可见而拒绝请求，
        这些文档将无法通过任何接口清理，只能人工介入数据库与向量库——即「删除知识库」
        的后续影响会被永久固化。
        """
        doc = self.get_document(doc_id)
        kb = self.kb_repo.get_by_id_including_deleted(doc.kb_id)
        deleted_at = datetime.utcnow()

        # 计数只在知识库本身仍存活时维护：知识库已删时其计数在删除时已归零，
        # 再减一次既无意义，也会掩盖真实的回收进度。
        if kb is not None and kb.deleted_at is None:
            if kb.document_count and kb.document_count > 0:
                self.kb_repo.update(kb, document_count=max(kb.document_count - 1, 0))
            if doc.chunk_count and kb.chunk_count and kb.chunk_count > 0:
                self.kb_repo.update(kb, chunk_count=max(kb.chunk_count - doc.chunk_count, 0))

        deleted_chunks = self._purge_document(
            doc,
            deleted_at,
            # 传指针而非让底层自己拼集合名：两代分块在不同集合，都要清理
            active_collection=kb.active_collection if kb is not None else None,
        )
        logger.info("Deleted document %s with %d chunks", doc_id, deleted_chunks)

        self.db.commit()

    # ── 分块查询 ──────────────────────────────────────────────────────────────

    def get_chunks(
        self,
        doc_id: str,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[List[KnowledgeChunk], int]:
        """获取文档的分块列表"""
        chunks = self.chunk_repo.list_by_document(doc_id=doc_id, page=page, page_size=page_size)
        total = self.chunk_repo.count_by_document(doc_id=doc_id)
        return chunks, total

    # ── 向量检索 ──────────────────────────────────────────────────────────────

    def search_with_diagnostics(
        self,
        kb_id: str,
        query: str,
        top_k: int = 5,
        score_threshold: Optional[float] = None,
        use_rerank: Optional[bool] = None,
        candidate_k: Optional[int] = None,
    ) -> SearchOutcome:
        """语义检索知识库（可选 CrossEncoder 精排），并返回诊断信息

        Args:
            kb_id: 知识库 ID（UUID 字符串）
            query: 查询文本
            top_k: 返回前 k 个结果
            score_threshold: 相似度下限；缺省时取配置 retrieval_score_threshold
            use_rerank: 是否启用精排；缺省时取配置 reranker_enabled。
                **关闭时行为与改造前严格等价**（只查 top_k 条、不做任何重排）。
            candidate_k: 精排前的宽召回条数；缺省时取配置 reranker_candidate_k。
                精排只能重排已召回的候选，候选集过小会直接限制精排的质量上限。

        Returns:
            :class:`SearchOutcome`。``results`` 为相关文档片段列表，按当前生效的
            排序策略降序；``degraded`` / ``reason`` 记录本次检索是否降级及原因，
            是区分「后端故障」与「确无相关内容」的唯一依据。片段字段说明：

            * ``score``            —— 生效排序的分数（精排开启时为归一化后的精排分数；
              混合检索生效时为**融合分数**；否则为稠密相似度）。
              **始终与返回顺序单调一致**。
            * ``retrieval_score``  —— 稠密召回相似度。保留它是为了区分「召回没捞到」
              与「捞到了但排太后」，是判断该上精排还是该改召回的依据。
              **混合检索生效时该字段可能缺失**：仅出现在稠密分支命中的条目上。
              词法分支独有的条目没有稠密相似度，此时不给字段而不是填 0.0——
              0.0 会把「稠密根本没召回到它」误读成「稠密认为它完全不相关」。
            * ``rerank_score``     —— 精排原始 logit（仅精排生效时存在）。
            * ``duplicate_count``  —— 本条内容被折叠掉的等值副本数（无副本时为 0）。
              存在它是为了让调用方能解释「结果条数为何少于 top_k」——那是去重生效
              的结果，而不是召回不足。
            * ``llm_content``      —— **喂给 LLM 的文本**（P4 上下文装配的产物）：
              出处标记 + 含前后邻块的窗口正文。``content`` 始终是本块原文，不参与
              装配——它同时是去重键与前端展示文本，被注入即变成脏数据。
            * ``context_header``   —— ``llm_content`` 前置的出处标记行（无出处信息
              时为 ``None``），例如 ``[《手册.pdf》 | § 3.2 | p.37–38]``。
            * ``context_expanded`` —— 是否真的拼入了邻块。为假有两种原因（开关关闭
              / 命中块本身无邻块），二者对消费方是同一件事，故不再细分。

        三个新键**恒显式出现**（``llm_content`` 至少等于 ``content``），理由同出处
        字段：消费方若按「键是否存在」判断，会把「该功能没实现」与「本块没有邻居」
        混为一谈。关闭 ``retrieval_context_header_enabled`` 且
        ``retrieval_neighbor_expansion=0`` 时，``llm_content`` 与 ``content`` 逐字符
        相等——这是本层的回滚开关。

        返回结果在去重开启时**按内容去重**：同一段落的多个等值副本只保留最高分的
        一份。这既避免副本并列占满 top_k 挤压其它段落，也避免重复内容被重复灌入
        LLM 上下文。

        混合检索（``retrieval_hybrid_enabled``）需要同时满足两个条件才启用：
        开关打开**且**该库集合为「命名稠密 + 命名稀疏」布局。任一不满足即退化为
        纯稠密。注意「布局」与「开关」是解耦的两件事：**集合布局由回填决定，
        开关只控制是否融合**。因此关闭开关是安全的回滚动作（仍返回正确的稠密结果），
        而混合布局的集合即使开关关闭也必须以 ``using="dense"`` 查询——否则 Qdrant
        会以 400 拒绝匿名向量查询。词法分支自身异常时同样只降级该分支并记录告警，
        不让一次增强失败升级为检索整体不可用。
        """
        if not query or not query.strip():
            raise ValidationException("Query cannot be empty")

        kb = self.get_knowledge_base(kb_id)

        threshold = (
            score_threshold
            if score_threshold is not None
            else config.retrieval_score_threshold
        )

        rerank_enabled = config.reranker_enabled if use_rerank is None else bool(use_rerank)
        dedup_enabled = config.retrieval_dedup_enabled
        # 宽召回仅对精排有意义：不精排时多召回只会增加回表与传输成本。
        fetch_k = max(top_k, candidate_k or config.reranker_candidate_k) if rerank_enabled else top_k
        # 去重会折叠等值副本，被折叠掉的候选位必须靠超额召回补回：
        # 否则「top_k=10」在副本存在时只返回不足 10 条不同内容——用户看到的是
        # 「结果变少了」，而真正的原因是坑位被副本吃掉，不是库里只有这么多内容。
        if dedup_enabled:
            fetch_k = max(fetch_k, top_k * max(1, config.retrieval_fetch_multiplier))

        # 对查询文本进行向量化
        embedding_client = get_embedding_client(model=kb.embedding_model)
        query_embedding = embedding_client.embed([query])[0]

        # 混合检索：**布局**决定「怎么查稠密」，**开关**决定「要不要跑词法」。
        # 二者必须解耦，否则会出现两个严重故障：
        #   1) 集合已是混合布局（命名稠密）但开关未开时，若仍发匿名向量查询，
        #      Qdrant 会以 400 拒绝——实测该状态下 100/100 查询全部失败；
        #   2) 关掉开关本应是安全的回滚动作，却会把检索变成全 0。
        # 因此 ``using`` 只由布局决定；开关只控制是否融合。
        # 集合由灰度 / 回滚指针解析：重建后指针指向新集合，为空时行为与改造前一致。
        # 写入侧（knowledge_processor）必须用同一个解析，否则会出现「写进 A、查 B」。
        collection_name = collection_name_for(kb_id, kb.active_collection)
        layout = collection_layout(collection_name)
        dense_using = NAMED_DENSE_VECTOR if layout == "hybrid" else None
        hybrid_active = config.retrieval_hybrid_enabled and layout == "hybrid"

        # 两路各自独立的召回条数：稠密的 fetch_k 由精排/去重需求推导，而词法是另一套
        # 排序，候选池过小会让它「有话说不出」。注意二者是**相加**关系，直接决定延迟。
        dense_fetch_k = fetch_k
        sparse_fetch_k = max(fetch_k, config.retrieval_sparse_top_k) if hybrid_active else 0

        # 从 Qdrant 检索相似文本（与离线评测共用同一召回实现，见 search_points）
        try:
            dense_points: List[RetrievedPoint] = search_points(
                collection_name=collection_name,
                query_vector=query_embedding,
                limit=dense_fetch_k,
                score_threshold=threshold,
                using=dense_using,
            )
        except Exception as exc:
            # Collection 不存在或 Qdrant 不可用：返回空结果而非中断调用链，但必须把
            # 原因带回调用方——否则「后端故障」与「确无相关内容」完全不可区分（P2-E）。
            reason = _classify_qdrant_failure(exc)
            log = logger.error if reason == DEGRADED_COLLECTION_NOT_FOUND else logger.warning
            log("Qdrant search failed on %s (%s): %s", collection_name, reason, exc)
            return SearchOutcome(
                results=[], degraded=True, reason=reason, collection=collection_name
            )

        sparse_points: List[RetrievedPoint] = []
        if hybrid_active:
            try:
                sparse_indices, sparse_values = default_encoder().query_vector(query)
                sparse_points = search_sparse_points(
                    collection_name=collection_name,
                    indices=sparse_indices,
                    values=sparse_values,
                    limit=sparse_fetch_k,
                )
            except Exception as exc:
                # 词法分支是**增强**而非必需：它失败不应把本来可用的稠密检索一起拖垮。
                # 与精排降级同一原则——单点故障不得升级为功能整体不可用。
                logger.warning(
                    "Sparse branch failed on %s, falling back to dense-only: %s",
                    collection_name,
                    exc,
                )
                sparse_points = []

        dense_ids = [point.id for point in dense_points]
        dense_scores_by_id = {point.id: point.score for point in dense_points}

        if sparse_points:
            # 融合实现见 app.utils.retrieval_fusion（线上与离线评测的唯一共用处）。
            # 注意不要改成服务端 RRF：实测等权 RRF 使 MRR@10 −7.33pp。
            ranked: List[tuple] = weighted_fuse(
                dense_ids,
                [point.score for point in dense_points],
                [point.id for point in sparse_points],
                [point.score for point in sparse_points],
                alpha=config.retrieval_hybrid_alpha,
            )
        else:
            # 纯稠密路径：与改造前严格等价（同样的顺序、同样的分数、同样的条数）
            ranked = list(zip(dense_ids, [point.score for point in dense_points]))

        if not ranked:
            return SearchOutcome(results=[], collection=collection_name)

        # 一次回表取回全部分块，避免逐条查询造成的 N+1
        chunk_map = {
            chunk.vector_id: chunk
            for chunk in self.chunk_repo.list_by_vector_ids(
                [point_id for point_id, _ in ranked]
            )
        }

        # 组装结果，保持融合后的相关度顺序
        chunks_data: List[Dict[str, Any]] = []
        # ORM 行按 chunk.id 暂存，供上下文装配使用：``chunk_epoch`` 与
        # ``heading_path_mixed`` 只在 ORM 行上，而它们不该进入对外响应契约。
        chunks_by_id: Dict[str, KnowledgeChunk] = {}
        for point_id, fused_score in ranked:
            chunk = chunk_map.get(point_id)
            if not chunk:
                continue
            chunks_by_id[chunk.id] = chunk
            item: Dict[str, Any] = {
                "id": chunk.id,
                "content": chunk.content,
                "score": fused_score,
                "doc_id": chunk.doc_id,
                "doc_name": chunk.document.file_name if chunk.document else None,
                "chunk_index": chunk.chunk_index,
                # 出处信息：供答案给出「出自第 37–38 页 / §3.2」这类可核对引用。
                # 四个键都**显式出现**（可能为 None），不做「有值才加键」的处理——
                # 消费方若按「键是否存在」判断，就会把「该格式没有页码」误读成
                # 「这个字段没实现」。可得性边界见 docs/rag-eval/PHASE5-REBUILD-PLAN.md §2.2：
                # PDF 有页码无标题路径（pypdf 只给文本流），md/docx 反之。
                #
                # ``source_page`` / ``source_page_end`` 是**闭区间**：块可以跨页（合并的
                # 必然结果），单值只能表达「从哪一页开始」，显示成「第 37 页」而块里
                # 含有第 38 页的内容就是沉默的错答。
                # ``heading_path_mixed`` 为真表示 ``heading_path`` 只标到了若干兄弟子节的
                # 公共祖先，块内并无该祖先自身的内容——消费方应呈现为「A 等小节」。
                "source_page": chunk.source_page,
                "source_page_end": chunk.source_page_end,
                "heading_path": chunk.heading_path,
                "heading_path_mixed": chunk.heading_path_mixed,
                # 块类型：供前端差异化展示（命中表格/代码时按纯文本渲染会丢掉列结构
                # 或换行），也供本方法的上下文装配给 LLM 加 ``表格`` / ``代码`` 提示。
                # 取值域见 ``app.utils.document.CHUNK_TYPES``；存量行由迁移回填为
                # ``text``，故此处不做 None 兜底。
                "chunk_type": chunk.chunk_type,
            }
            # ``retrieval_score`` 仅在稠密分支命中时给出：词法独有项没有稠密相似度，
            # 用 0.0 顶替会把「稠密根本没召回到它」误读成「稠密认为它完全不相关」，
            # 而这正是诊断时最需要区分的两件事。
            if point_id in dense_scores_by_id:
                item["retrieval_score"] = dense_scores_by_id[point_id]
            chunks_data.append(item)

        # 折叠必须在精排**之前**：否则精排的候选预算会被等值副本吃掉，
        # 且会对同一段落反复推理，纯属浪费算力。
        if dedup_enabled:
            chunks_data = self._dedupe_by_content(chunks_data)

        if rerank_enabled and len(chunks_data) > 1:
            chunks_data = self._apply_rerank(query, chunks_data)

        # 上下文装配必须在**截断到 top_k 之后**：邻块扩展要回表取行，对最终不会
        # 返回的候选做扩展纯属浪费（宽召回 20 条时是 15 次无用查询）。
        final = chunks_data[:top_k]
        self._assemble_context(final, chunks_by_id)

        return SearchOutcome(results=final, collection=collection_name)

    def search(
        self,
        kb_id: str,
        query: str,
        top_k: int = 5,
        score_threshold: Optional[float] = None,
        use_rerank: Optional[bool] = None,
        candidate_k: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """语义检索知识库，仅返回结果列表

        保留本方法是为了兼容既有调用方（REST 路由、Agent 工具、工作流节点、离线
        评测）的 list 契约——把返回类型改成对象属破坏性变更，而诊断信息的价值
        并不足以抵偿联调成本。需要区分「故障」与「无结果」的调用方请改用
        :meth:`search_with_diagnostics`。
        """
        return self.search_with_diagnostics(
            kb_id=kb_id,
            query=query,
            top_k=top_k,
            score_threshold=score_threshold,
            use_rerank=use_rerank,
            candidate_k=candidate_k,
        ).results

    # ── 上下文装配（P4）──────────────────────────────────────────────────────

    def _assemble_context(
        self,
        items: List[Dict[str, Any]],
        chunks_by_id: Dict[str, KnowledgeChunk],
    ) -> None:
        """就地为结果装配 ``llm_content`` / ``context_header`` / ``context_expanded``

        三个键**无论开关如何恒被写入**，使响应契约不随配置漂移——否则前端与
        Agent 工具就要按「配置项是否开启」分支处理字段缺失，而这种分支在配置
        变更时不会有任何提示。

        ``content`` 在这里是**只读**的：装配结果一律写入 ``llm_content``。

        Args:
            items: 已截断到 top_k 的结果字典（原地修改）
            chunks_by_id: ``chunk.id -> ORM 行``，提供只有 ORM 行才有的
                ``chunk_epoch`` / ``heading_path_mixed``
        """
        header_enabled = config.retrieval_context_header_enabled
        radius = max(0, int(config.retrieval_neighbor_expansion))
        windows = self._neighbor_windows(items, chunks_by_id, radius) if radius else {}

        for idx, item in enumerate(items):
            chunk = chunks_by_id.get(item["id"])

            # 响应内编号（与 Agent 侧的「轮次内编号」是两套作用域，见
            # docs/plan-citation-traceability.md §Phase 1）。用于检索页展示
            # 「来源 1/2/3」，恒为数组下标 + 1，与开关、配置无关。
            item["marker"] = idx + 1

            header: Optional[str] = None
            if header_enabled and chunk is not None:
                header = build_context_header(
                    doc_name=item.get("doc_name"),
                    heading_path=chunk.heading_path,
                    heading_path_mixed=bool(chunk.heading_path_mixed),
                    page=chunk.source_page,
                    page_end=chunk.source_page_end,
                    # 类型取自 ORM 行而非 ``item``：``item`` 是服务层字典，字段可能
                    # 在去重/精排过程中被重建，而 ORM 行是唯一权威来源。
                    chunk_type=chunk.chunk_type,
                )

            body, expanded = windows.get(item["id"], (item["content"], False))
            if not body:
                # 空正文的极端情形：邻块裁剪后窗口为空（块内容完全被前一块覆盖）。
                # 退回原文而不是给出空串——给出空串等于让模型看不到任何证据。
                body = item["content"]
            item["context_header"] = header
            item["context_expanded"] = expanded
            item["llm_content"] = f"{header}\n\n{body}" if header else body

    def _neighbor_windows(
        self,
        items: List[Dict[str, Any]],
        chunks_by_id: Dict[str, KnowledgeChunk],
        radius: int,
    ) -> Dict[str, tuple]:
        """为每个命中块构造含前后邻块的窗口，返回 ``chunk.id -> (窗口文本, 是否扩展)``

        **本方法是继 ``list_by_vector_ids`` 之后第二条把内容送进 LLM 上下文的路径**，
        因此必须受同样的约束：租户隔离、文档存活、代次自洽（见
        :meth:`KnowledgeChunkRepository.list_neighbors`）。

        实现要点：

        * 按 ``(doc_id, chunk_epoch)`` 归组后**每组合并一次查询**，而不是每个命中块
          查一次——top_k=10、radius=1 时把 10 次往返压成 1–2 次。
        * 邻块取自**命中块自身的代次**，不是文档的当前代次：回滚到旧集合后命中块
          属旧代，用当前代过滤会让窗口静默退化成单块。
        * 索引缺失（重建时序错位、行被清理）时窗口只含实际存在的块，不外扩、不补空。
        """
        wanted: Dict[tuple, List[int]] = {}
        for item in items:
            chunk = chunks_by_id.get(item["id"])
            if chunk is None:
                continue
            key = (chunk.doc_id, chunk.chunk_epoch)
            indexes = wanted.setdefault(key, [])
            for index in collect_window_indexes(chunk.chunk_index, radius):
                if index not in indexes:
                    indexes.append(index)

        contents: Dict[tuple, str] = {}
        for (doc_id, epoch), indexes in wanted.items():
            rows = self.chunk_repo.list_neighbors(
                doc_id=doc_id,
                chunk_epoch=epoch,
                chunk_indexes=iter_unique(indexes),
            )
            for row in rows:
                contents[(doc_id, epoch, row.chunk_index)] = row.content

        windows: Dict[str, tuple] = {}
        for item in items:
            chunk = chunks_by_id.get(item["id"])
            if chunk is None:
                windows[item["id"]] = (item["content"], False)
                continue
            key = (chunk.doc_id, chunk.chunk_epoch)
            texts = [
                contents[(key[0], key[1], index)]
                for index in collect_window_indexes(chunk.chunk_index, radius)
                if (key[0], key[1], index) in contents
            ]
            if not texts:
                windows[item["id"]] = (item["content"], False)
                continue
            windows[item["id"]] = (
                join_window(texts, config.chunk_overlap),
                len(texts) > 1,
            )
        return windows

    @staticmethod
    def _dedupe_by_content(chunks_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """按内容折叠等值副本，每个内容只保留首个（即最高分）副本

        **为什么必须有这一层**：同一段落在知识库中可能存在多份等值副本——同一份
        文档被重复上传（每次上传都产生新的 ``doc_id``，而向量 id 由
        ``uuid5(doc.id + index)`` 派生，因此副本之间互不覆盖），或不同文档内容重合。
        每个副本都是独立的 Qdrant point，会各自占据一个候选位。不折叠的后果有两层：
        界面上同一段落重复出现、挤压其它段落的召回机会，以及重复内容被重复灌入
        LLM 上下文，稀释有效信息密度。

        **归一化只做空白处理**：去除首尾空白并折叠内部连续空白。中文正文的差异
        几乎都来自分块边界的空白；而做大小写折叠会把 ``Transformer`` 与
        ``transformer`` 这类在代码语境下可能确有区别的片段误判为同一段，属于过度
        合并，因此不采用。

        Args:
            chunks_data: 已按分数降序排列的候选分块

        Returns:
            折叠后的候选列表，保持原有相对顺序。存活项的 ``duplicate_count`` 记录
            被折叠的副本数（无副本时为 0），供调用方解释结果条数。
        """
        seen: Dict[str, Dict[str, Any]] = {}
        deduped: List[Dict[str, Any]] = []

        for item in chunks_data:
            key = " ".join((item.get("content") or "").split())
            kept = seen.get(key)
            if kept is not None:
                kept["duplicate_count"] += 1
                continue
            item["duplicate_count"] = 0
            seen[key] = item
            deduped.append(item)

        folded = len(chunks_data) - len(deduped)
        if folded:
            logger.info(
                "Deduplicated %d equivalent chunk copies (%d -> %d candidates)",
                folded, len(chunks_data), len(deduped),
            )
        return deduped

    @staticmethod
    def _apply_rerank(query: str, chunks_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """按精排分数重排 ``chunks_data``

        精排是**增强**而非必需环节：模型不可用时应回落到稠密排序并记录日志，
        而不是让检索整体失败——否则一次权重缺失就会让整个知识库功能不可用。
        """
        try:
            reranker = get_reranker()
            ordered = reranker.rerank(
                query, [(item["id"], item["content"]) for item in chunks_data]
            )
        except RerankerUnavailable as exc:
            logger.warning("Reranker unavailable, falling back to dense order: %s", exc)
            return chunks_data

        rank = {chunk_id: position for position, (chunk_id, _) in enumerate(ordered)}
        scores = {chunk_id: score for chunk_id, score in ordered}

        for item in chunks_data:
            logit = scores.get(item["id"])
            if logit is None:
                continue
            item["rerank_score"] = logit
            item["score"] = _sigmoid(logit)

        return sorted(chunks_data, key=lambda item: rank.get(item["id"], len(rank)))
