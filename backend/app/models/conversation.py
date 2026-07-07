from datetime import datetime
from typing import Optional, List

from sqlalchemy import String, Text, DateTime, func
from sqlalchemy.orm import mapped_column, Mapped, relationship
from sqlalchemy import ForeignKey

from app.core.database import Base

import uuid


class Conversation(Base):
    """对话模型"""
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)

    # 关联Agent
    agent_id: Mapped[str] = mapped_column(String(36), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)

    # 对话信息
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="新对话")

    # 时间戳
    created_by: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # 关系
    agent: Mapped["Agent"] = relationship("Agent", back_populates="conversations")
    messages: Mapped[List["Message"]] = relationship(
        "Message", back_populates="conversation", cascade="all, delete-orphan", order_by="Message.created_at"
    )
