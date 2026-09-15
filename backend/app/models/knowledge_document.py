from sqlalchemy import Column, Integer, String, Text, DateTime, func, ForeignKey, Enum
from sqlalchemy.orm import mapped_column, Mapped, relationship
from datetime import datetime
import enum
import uuid

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

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    kb_id: Mapped[str] = mapped_column(String(36), ForeignKey("knowledge_bases.id"), nullable=False, index=True)
    
    # 文件信息
    file_name = Column(String(255), nullable=False)
    file_type = Column(String(50), nullable=False)  # pdf, docx, txt, md
    file_size = Column(Integer, nullable=False)  # 字节
    file_url = Column(String(512), nullable=True)  # 文件存储URL（如S3）
    
    # 内容元数据
    original_content = Column(Text, nullable=True)  # 原始文本（存储解析后的全文）
    chunk_count = Column(Integer, default=0)  # 该文档的分块数

    # 该文档**当前生效**的分块代次（"448-64"），与 knowledge_chunks.chunk_epoch 配对。
    # 重建期间新旧两代分块行会同时存活（旧行支撑回滚窗口），因此「这份文档现在该看
    # 哪一代」必须显式记录，否则分块列表与计数会把两代混在一起。
    # **不能**用 config.chunk_epoch 顶替：配置在重建前就已变成新值，
    # 拿它过滤会让该文档的分块列表在重建完成前静默返回空。NULL 表示从未产出分块。
    active_chunk_epoch = Column(String(32), nullable=True)
    
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
