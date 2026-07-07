from datetime import datetime
from typing import Optional, List

from sqlalchemy import String, Text, DateTime, Boolean, JSON, func
from sqlalchemy.orm import mapped_column, Mapped, relationship

from app.core.database import Base

import uuid


class Agent(Base):
    """Agent模型"""
    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)

    # 基本信息
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    avatar: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Agent配置
    system_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    model_id: Mapped[str] = mapped_column(String(36), nullable=False)  # 关联AI模型ID
    temperature: Mapped[float] = mapped_column(default=0.7, nullable=False)
    max_tokens: Mapped[int] = mapped_column(default=2000, nullable=False)

    # 状态
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)  # draft | published | archived

    # 时间戳
    created_by: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # 关系
    tools: Mapped[List["AgentTool"]] = relationship("AgentTool", back_populates="agent", cascade="all, delete-orphan")
    conversations: Mapped[List["Conversation"]] = relationship(
        "Conversation", back_populates="agent", cascade="all, delete-orphan"
    )
