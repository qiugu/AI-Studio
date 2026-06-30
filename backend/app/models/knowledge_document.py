from sqlalchemy import Column, Integer, String, Text, DateTime, func, ForeignKey, Enum
from sqlalchemy.orm import relationship
from datetime import datetime
import enum

from app.core.database import Base


class DocumentStatus(str, enum.Enum):
    """文档处理状态"""
    PENDING = "pending"        # 待处理
    PROCESSING = "processing"  # 处理中
    COMPLETED = "completed"    # 完成
    FAILED = "failed"          # 失败


class KnowledgeDocument(Base):
    """知识库文档"""
    __tablename__ = "knowledge_documents"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, nullable=False, index=True)
    kb_id = Column(Integer, ForeignKey("knowledge_bases.id"), nullable=False, index=True)
    
    # 文件信息
    file_name = Column(String(255), nullable=False)
    file_type = Column(String(50), nullable=False)  # pdf, docx, txt, md
    file_size = Column(Integer, nullable=False)  # 字节
    file_url = Column(String(512), nullable=True)  # 文件存储URL（如S3）
    
    # 内容元数据
    original_content = Column(Text, nullable=True)  # 原始文本（存储解析后的全文）
    chunk_count = Column(Integer, default=0)  # 该文档的分块数
    
    # 处理状态与错误信息
    status = Column(Enum(DocumentStatus), default=DocumentStatus.PENDING, nullable=False, index=True)
    error_message = Column(Text, nullable=True)  # 失败时的错误信息
    processed_at = Column(DateTime, nullable=True)  # 处理完成时间
    
    # 时间戳
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    deleted_at = Column(DateTime, nullable=True)  # 软删除
    
    # 关系
    knowledge_base = relationship("KnowledgeBase", back_populates="documents")
    chunks = relationship("KnowledgeChunk", back_populates="document", cascade="all, delete-orphan")
