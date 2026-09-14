"""知识库服务"""
import logging
import math
import os
import shutil
from pathlib import Path
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
    get_or_create_collection,
    get_qdrant_client,
    get_vector_size_for_model,
    search_points,
)
from app.services.knowledge_processor import process_document_task
from app.utils.embedding import get_embedding_client
from app.utils.reranker import RerankerUnavailable, get_reranker

logger = logging.getLogger(__name__)


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
        """软删除知识库"""
        kb = self.get_knowledge_base(kb_id)
        self.kb_repo.update(kb, deleted_at=datetime.utcnow())
        self.db.commit()

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

    def delete_document(self, doc_id: str) -> None:
        """软删除文档（并级联清理分块与向量）

        顺序不可调整：必须**先**取出未删除的分块用于清理向量，**再**批量软删除分块。
        若先软删除分块，``list_by_doc_id`` 将查不到任何记录，向量清理会静默跳过，
        残留向量继续参与召回（这正是 A2 与 D9 叠加后的表现）。

        D9 处置说明：软删除文档时若不同步软删除分块，检索回表的
        ``deleted_at IS NULL`` 过滤就形同虚设，已下架内容仍会被检索命中。
        """
        doc = self.get_document(doc_id)
        kb = self.get_knowledge_base(doc.kb_id)
        deleted_at = datetime.utcnow()
        self.doc_repo.update(doc, deleted_at=deleted_at)

        if kb.document_count and kb.document_count > 0:
            self.kb_repo.update(kb, document_count=max(kb.document_count - 1, 0))
        if doc.chunk_count and kb.chunk_count and kb.chunk_count > 0:
            self.kb_repo.update(kb, chunk_count=max(kb.chunk_count - doc.chunk_count, 0))

        # 1) 先取未删除的分块，用于清理对应的 Qdrant 向量
        chunks = self.chunk_repo.list_by_doc_id(doc_id)

        point_ids = [chunk.vector_id for chunk in chunks if chunk.vector_id]
        if point_ids:
            qdrant = get_qdrant_client()
            collection_name = f"kb_{doc.kb_id}"
            try:
                qdrant.delete(
                    collection_name=collection_name,
                    points_selector=PointIdsList(points=point_ids),
                )
            except Exception as exc:
                # 向量清理失败不应阻断业务主流程，但必须留下可追溯的日志
                logger.warning(
                    "Failed to delete %d vectors from %s (doc=%s): %s",
                    len(point_ids), collection_name, doc_id, exc,
                )

        # 2) 再级联软删除分块，使检索回表的 deleted_at 过滤真正生效（D9）
        deleted_chunks = self.chunk_repo.soft_delete_by_doc_id(doc_id, deleted_at)
        logger.info("Soft-deleted document %s with %d chunks", doc_id, deleted_chunks)

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

    def search(
        self,
        kb_id: str,
        query: str,
        top_k: int = 5,
        score_threshold: Optional[float] = None,
        use_rerank: Optional[bool] = None,
        candidate_k: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """语义检索知识库（可选 CrossEncoder 精排）

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
            相关文档片段列表，按当前生效的排序策略降序。字段说明：

            * ``score``            —— 生效排序的分数（精排开启时为归一化后的精排分数，
              否则为稠密相似度）。**始终与返回顺序单调一致**。
            * ``retrieval_score``  —— 稠密召回相似度。保留它是为了区分「召回没捞到」
              与「捞到了但排太后」，是判断该上精排还是该改召回的依据。
            * ``rerank_score``     —— 精排原始 logit（仅精排生效时存在）。
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
        # 宽召回仅对精排有意义：不精排时多召回只会增加回表与传输成本。
        fetch_k = max(top_k, candidate_k or config.reranker_candidate_k) if rerank_enabled else top_k

        # 对查询文本进行向量化
        embedding_client = get_embedding_client(model=kb.embedding_model)
        query_embedding = embedding_client.embed([query])[0]

        # 从 Qdrant 检索相似文本（与离线评测共用同一召回实现，见 search_points）
        collection_name = f"kb_{kb_id}"

        try:
            results = search_points(
                collection_name=collection_name,
                query_vector=query_embedding,
                limit=fetch_k,
                score_threshold=threshold,
            )
        except Exception as exc:
            # Collection 不存在或 Qdrant 不可用：返回空结果而非中断调用链
            logger.warning("Qdrant search failed on %s: %s", collection_name, exc)
            return []

        if not results:
            return []

        # 一次回表取回全部分块，避免逐条查询造成的 N+1
        chunk_map = {
            chunk.vector_id: chunk
            for chunk in self.chunk_repo.list_by_vector_ids([point.id for point in results])
        }

        # 组装结果，保持 Qdrant 返回的相关度顺序
        chunks_data: List[Dict[str, Any]] = []
        for point in results:
            chunk = chunk_map.get(point.id)
            if not chunk:
                continue
            chunks_data.append({
                "id": chunk.id,
                "content": chunk.content,
                "score": point.score,
                "retrieval_score": point.score,
                "doc_id": chunk.doc_id,
                "doc_name": chunk.document.file_name if chunk.document else None,
                "chunk_index": chunk.chunk_index,
            })

        if rerank_enabled and len(chunks_data) > 1:
            chunks_data = self._apply_rerank(query, chunks_data)

        return chunks_data[:top_k]

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
