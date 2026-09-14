from datetime import datetime
from typing import Optional, List

from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_

from app.models.knowledge_base import KnowledgeBase
from app.models.knowledge_document import KnowledgeDocument, DocumentStatus
from app.models.knowledge_chunk import KnowledgeChunk
from app.repositories.base import BaseRepository


class KnowledgeBaseRepository(BaseRepository[KnowledgeBase]):
    """知识库 Repository"""

    def __init__(self, db: Session, tenant_id: str):
        super().__init__(KnowledgeBase, db, tenant_id)


class KnowledgeDocumentRepository(BaseRepository[KnowledgeDocument]):
    """知识库文档 Repository"""

    def __init__(self, db: Session, tenant_id: str):
        super().__init__(KnowledgeDocument, db, tenant_id)

    def list_by_kb(
        self,
        kb_id: str,
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

    def count_by_kb(self, kb_id: str, status: Optional[DocumentStatus] = None) -> int:
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

    def __init__(self, db: Session, tenant_id: str):
        super().__init__(KnowledgeChunk, db, tenant_id)

    def list_by_document(
        self,
        doc_id: str,
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

    def count_by_document(self, doc_id: str) -> int:
        """统计文档中的分块数"""
        return self.db.query(KnowledgeChunk).filter(
            and_(
                KnowledgeChunk.tenant_id == self.tenant_id,
                KnowledgeChunk.doc_id == doc_id,
                KnowledgeChunk.deleted_at.is_(None),
            )
        ).count()

    def get_by_vector_id(self, vector_id: str) -> Optional[KnowledgeChunk]:
        """按 Qdrant vector_id 查询单个分块

        注意：必须带 tenant_id 过滤，否则可能读到其他租户的分块。
        """
        return self.db.query(KnowledgeChunk).filter(
            and_(
                KnowledgeChunk.tenant_id == self.tenant_id,
                KnowledgeChunk.vector_id == vector_id,
                KnowledgeChunk.deleted_at.is_(None),
            )
        ).first()

    def list_by_vector_ids(self, vector_ids: List[str]) -> List[KnowledgeChunk]:
        """按一组 Qdrant vector_id 批量查询分块

        检索回表时使用，避免逐条 get_by_vector_id 造成的 N+1 查询；
        同时预加载 document 关系，供结果中回填文档名。
        """
        if not vector_ids:
            return []
        return (
            self.db.query(KnowledgeChunk)
            .options(joinedload(KnowledgeChunk.document))
            .filter(
                and_(
                    KnowledgeChunk.tenant_id == self.tenant_id,
                    KnowledgeChunk.vector_id.in_(vector_ids),
                    KnowledgeChunk.deleted_at.is_(None),
                )
            )
            .all()
        )

    def list_by_doc_id(self, doc_id: str) -> List[KnowledgeChunk]:
        """查询指定文档下的全部分块（用于清理向量等场景）"""
        return self.db.query(KnowledgeChunk).filter(
            and_(
                KnowledgeChunk.tenant_id == self.tenant_id,
                KnowledgeChunk.doc_id == doc_id,
                KnowledgeChunk.deleted_at.is_(None),
            )
        ).all()

    def soft_delete_by_doc_id(self, doc_id: str, deleted_at: datetime) -> int:
        """批量软删除指定文档下的全部分块，返回受影响行数

        **为什么必须级联**：检索回表路径（``list_by_vector_ids``）已经过滤
        ``deleted_at IS NULL``，但软删除文档时若只标记文档而不标记分块，
        该过滤条件就形同虚设——已下架文档的分块仍会被检索命中并进入回答上下文。
        即「过滤逻辑本身是对的，失效原因是写入侧从未把分块标记为已删除」。

        Args:
            doc_id: 文档 ID
            deleted_at: 统一的删除时间戳，由调用方传入以保证同一次操作时间一致
        """
        return (
            self.db.query(KnowledgeChunk)
            .filter(
                and_(
                    KnowledgeChunk.tenant_id == self.tenant_id,
                    KnowledgeChunk.doc_id == doc_id,
                    KnowledgeChunk.deleted_at.is_(None),
                )
            )
            .update({KnowledgeChunk.deleted_at: deleted_at}, synchronize_session=False)
        )
