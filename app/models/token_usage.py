from datetime import datetime
from typing import Optional

from sqlalchemy import String, DateTime, BigInteger, func
from sqlalchemy.orm import mapped_column, Mapped

from app.core.database import Base

import uuid


class TokenUsage(Base):
    """Token使用统计模型"""
    __tablename__ = "token_usages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)

    # 关联信息
    agent_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    model_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    user_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    conversation_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)

    # Token统计
    prompt_tokens: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    total_tokens: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)

    # 时间戳
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
