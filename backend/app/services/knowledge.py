"""知识库服务"""
import os
import shutil
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime

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
)
from app.services.knowledge_processor import process_document_task
from app.utils.embedding import get_embedding_client


class KnowledgeBaseService:
    """知识库服务"""

    def __init__(self, db: Session, tenant_id: int):
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
        embedding_model: str = "BAAI/bge-m3",
    ) -> KnowledgeBase:
        """创建知识库"""
        if not name or not name.strip():
            raise ValidationException("Knowledge base name cannot be empty")

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

    def get_knowledge_base(self, kb_id: int) -> KnowledgeBase:
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
        kb_id: int,
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

    def delete_knowledge_base(self, kb_id: int) -> None:
        """软删除知识库"""
        kb = self.get_knowledge_base(kb_id)
        self.kb_repo.update(kb, deleted_at=datetime.utcnow())
        self.db.commit()

    # ── 文档管理 ──────────────────────────────────────────────────────────────

    def upload_document(
        self,
        kb_id: int,
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
        dest_dir = Path(config.upload_dir) / str(self.tenant_id) / str(kb_id) / str(doc.id)
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

    def get_document(self, doc_id: int) -> KnowledgeDocument:
        """获取文档详情"""
        doc = self.doc_repo.get_by_id(doc_id)
        if not doc:
            raise NotFoundException("KnowledgeDocument", doc_id)
        return doc

    def list_documents(
        self,
        kb_id: int,
        status: Optional[DocumentStatus] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[List[KnowledgeDocument], int]:
        """列出知识库中的文档"""
        docs = self.doc_repo.list_by_kb(kb_id=kb_id, status=status, page=page, page_size=page_size)
        total = self.doc_repo.count_by_kb(kb_id=kb_id, status=status)
        return docs, total

    def delete_document(self, doc_id: int) -> None:
        """软删除文档"""
        doc = self.get_document(doc_id)
        kb = self.get_knowledge_base(doc.kb_id)
        self.doc_repo.update(doc, deleted_at=datetime.utcnow())

        if kb.document_count and kb.document_count > 0:
            self.kb_repo.update(kb, document_count=max(kb.document_count - 1, 0))
        if doc.chunk_count and kb.chunk_count and kb.chunk_count > 0:
            self.kb_repo.update(kb, chunk_count=max(kb.chunk_count - doc.chunk_count, 0))

        # 同时删除对应的 Qdrant 向量
        chunks = self.db.query(KnowledgeChunk).filter(
            KnowledgeChunk.doc_id == doc_id,
            KnowledgeChunk.deleted_at.is_(None),
        ).all()
        
        qdrant = get_qdrant_client()
        collection_name = f"kb_{doc.kb_id}"
        for chunk in chunks:
            if chunk.vector_id:
                try:
                    qdrant.delete(
                        collection_name=collection_name,
                        points_selector=chunk.vector_id,
                    )
                except Exception:
                    pass
        
        self.db.commit()

    # ── 分块查询 ──────────────────────────────────────────────────────────────

    def get_chunks(
        self,
        doc_id: int,
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
        kb_id: int,
        query: str,
        top_k: int = 5,
        score_threshold: float = 0.5,
    ) -> List[Dict[str, Any]]:
        """
        语义检索知识库

        Args:
            kb_id: 知识库ID
            query: 查询文本
            top_k: 返回前k个结果
            score_threshold: 相似度阈值

        Returns:
            相关文档片段列表，包含内容和相似度评分
        """
        kb = self.get_knowledge_base(kb_id)

        # 对查询文本进行向量化
        embedding_client = get_embedding_client(model=kb.embedding_model)
        query_embedding = embedding_client.embed([query])[0]

        # 从 Qdrant 检索相似文本
        qdrant = get_qdrant_client()
        collection_name = f"kb_{kb_id}"

        try:
            results = qdrant.search(
                collection_name=collection_name,
                query_vector=query_embedding,
                limit=top_k,
                score_threshold=score_threshold,
            )
        except Exception as e:
            # Collection 不存在或其他错误
            return []

        # 获取对应的分块内容
        chunks_data = []
        for result in results:
            chunk = self.chunk_repo.get_by_vector_id(str(result.id))
            if chunk:
                chunks_data.append({
                    "id": chunk.id,
                    "content": chunk.content,
                    "score": result.score,
                    "doc_id": chunk.doc_id,
                    "doc_name": chunk.document.file_name if chunk.document else None,
                    "chunk_index": chunk.chunk_index,
                })

        return chunks_data
