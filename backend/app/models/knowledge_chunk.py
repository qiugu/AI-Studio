from sqlalchemy import Column, Integer, String, Text, DateTime, func, ForeignKey, LargeBinary
from sqlalchemy.orm import mapped_column, Mapped, relationship
from datetime import datetime
import uuid

from app.core.database import Base


class KnowledgeChunk(Base):
    """知识库文档分块（文本片段）"""
    __tablename__ = "knowledge_chunks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    kb_id: Mapped[str] = mapped_column(String(36), ForeignKey("knowledge_bases.id"), nullable=False, index=True)
    doc_id: Mapped[str] = mapped_column(String(36), ForeignKey("knowledge_documents.id"), nullable=False, index=True)
    
    # 分块内容与元数据
    content = Column(Text, nullable=False)  # 分块文本
    chunk_index = Column(Integer, nullable=False)  # 在文档中的序号（从0开始）
    source_page = Column(Integer, nullable=True)  # PDF页码（可选）
    
    # 向量ID（指向Qdrant中的point_id）
    vector_id = Column(String(255), nullable=True, unique=True)  # Qdrant中的point_id（UUID格式）
    
    # 时间戳
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    deleted_at = Column(DateTime, nullable=True)  # 软删除
    
    # 关系
    document = relationship("KnowledgeDocument", back_populates="chunks")
