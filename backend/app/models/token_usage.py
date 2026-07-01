from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, String, DateTime, func
from sqlalchemy.orm import mapped_column, Mapped

from app.core.database import Base


class TokenUsage(Base):
    """Token使用统计模型"""
    __tablename__ = "token_usages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)

    # 关联信息
    agent_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, index=True)
    model_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, index=True)
    conversation_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, index=True)

    # Token统计
    prompt_tokens: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    total_tokens: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)

    # 时间戳
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)