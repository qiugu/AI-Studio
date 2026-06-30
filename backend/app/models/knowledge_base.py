from sqlalchemy import Column, Integer, String, Text, DateTime, func, BigInteger
from sqlalchemy.orm import relationship
from datetime import datetime

from app.core.database import Base


class KnowledgeBase(Base):
    """知识库模型"""
    __tablename__ = "knowledge_bases"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, nullable=False, index=True)
    
    # 基本信息
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    embedding_model = Column(String(255), default="text-embedding-3-small", nullable=False)  # Embedding模型标识
    
    # 统计信息
    document_count = Column(Integer, default=0)  # 文档数
    chunk_count = Column(BigInteger, default=0)  # 分块总数
    
    # 状态与时间戳
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    deleted_at = Column(DateTime, nullable=True)  # 软删除
    
    # 关系
    documents = relationship("KnowledgeDocument", back_populates="knowledge_base", cascade="all, delete-orphan")
