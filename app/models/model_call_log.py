from typing import Optional
from datetime import datetime

from sqlalchemy.orm import mapped_column, Mapped
from sqlalchemy import String, DateTime, BigInteger, Integer, Text, func

from app.core.database import Base

import uuid


class ModelCallLog(Base):
    """模型调用日志模型：每次 LLM 调用后记录 token 用量与状态。"""

    __tablename__ = "model_call_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)

    user_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    agent_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    model_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    provider_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    conversation_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)

    # Token 统计
    prompt_tokens: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    total_tokens: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)

    # 调用状态
    latency_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="success", nullable=False)  # success/error
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
