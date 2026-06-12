from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, Text, JSON, String, Integer, DateTime, func, ForeignKey
from sqlalchemy.orm import mapped_column, Mapped

from app.core.database import Base


class PromptTestLog(Base):
    __tablename__ = "prompt_test_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    prompt_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("prompts.id", ondelete="CASCADE"), nullable=False, index=True)
    version_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("prompt_versions.id", ondelete="SET NULL"), nullable=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    model_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    input_vars: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    rendered_content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    result_content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    prompt_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # status: success | error
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="success")
    error_msg: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, server_default=func.now())
