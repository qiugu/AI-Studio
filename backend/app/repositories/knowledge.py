from typing import Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.models.knowledge_base import KnowledgeBase
from app.models.knowledge_document import KnowledgeDocument, DocumentStatus
from app.models.knowledge_chunk import KnowledgeChunk
from app.repositories.base import BaseRepository


class KnowledgeBaseRepository(BaseRepository[KnowledgeBase]):
    """知识库 Repository"""

    def __init__(self, db: Session, tenant_id: int):
        super().__init__(KnowledgeBase, db, tenant_id)


class KnowledgeDocumentRepository(BaseRepository[KnowledgeDocument]):
    """知识库文档 Repository"""

    def __init__(self, db: Session, tenant_id: int):
        super().__init__(KnowledgeDocument, db, tenant_id)

    def list_by_kb(
        self,
        kb_id: int,
        status: Optional[DocumentStatus] = None,
        page: int = 1,
        page_size: int = 10,
        order_by: Optional[str] = 'created_at desc',
    ) -> List[KnowledgeDocument]:
        """按知识库ID查询文档"""
        query = self.db.query(KnowledgeDocument).filter(
            and_(
                KnowledgeDocument.tenant_id == self.tenant_id,
                KnowledgeDocument.kb_id == kb_id,
                KnowledgeDocument.deleted_at.is_(None),
            )
        ).order_by(KnowledgeDocument.created_at.desc())
        if status:
            query = query.filter(KnowledgeDocument.status == status)
        
        offset = (page - 1) * page_size
        return query.offset(offset).limit(page_size).all()

    def count_by_kb(self, kb_id: int, status: Optional[DocumentStatus] = None) -> int:
        """统计知识库中的文档数"""
        query = self.db.query(KnowledgeDocument).filter(
            and_(
                KnowledgeDocument.tenant_id == self.tenant_id,
                KnowledgeDocument.kb_id == kb_id,
                KnowledgeDocument.deleted_at.is_(None),
            )
        )
        if status:
            query = query.filter(KnowledgeDocument.status == status)
        return query.count()


class KnowledgeChunkRepository(BaseRepository[KnowledgeChunk]):
    """知识库分块 Repository"""

    def __init__(self, db: Session, tenant_id: int):
        super().__init__(KnowledgeChunk, db, tenant_id)

    def list_by_document(
        self,
        doc_id: int,
        page: int = 1,
        page_size: int = 20,
    ) -> List[KnowledgeChunk]:
        """按文档ID查询分块"""
        query = self.db.query(KnowledgeChunk).filter(
            and_(
                KnowledgeChunk.tenant_id == self.tenant_id,
                KnowledgeChunk.doc_id == doc_id,
                KnowledgeChunk.deleted_at.is_(None),
            )
        )
        offset = (page - 1) * page_size
        return query.offset(offset).limit(page_size).all()

    def count_by_document(self, doc_id: int) -> int:
        """统计文档中的分块数"""
        return self.db.query(KnowledgeChunk).filter(
            and_(
                KnowledgeChunk.tenant_id == self.tenant_id,
                KnowledgeChunk.doc_id == doc_id,
                KnowledgeChunk.deleted_at.is_(None),
            )
        ).count()

    def get_by_vector_id(self, vector_id: str) -> Optional[KnowledgeChunk]:
        """按Qdrant vector_id查询分块"""
        return self.db.query(KnowledgeChunk).filter(
            KnowledgeChunk.vector_id == vector_id,
            KnowledgeChunk.deleted_at.is_(None),
        ).first()
