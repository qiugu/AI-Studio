from datetime import datetime
from typing import Optional

from sqlalchemy import Integer, Text, JSON, Boolean, DateTime, func, ForeignKey, UniqueConstraint, String
from sqlalchemy.orm import mapped_column, Mapped

from app.core.database import Base

import uuid


class PromptVersion(Base):
    __tablename__ = "prompt_versions"
    __table_args__ = (UniqueConstraint("prompt_id", "version_number", name="uq_prompt_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    prompt_id: Mapped[str] = mapped_column(String(36), ForeignKey("prompts.id", ondelete="CASCADE"), nullable=False, index=True)
    # 纵深防御：prompt_versions 本身缺少 tenant_id，导致按版本查询无法在 DB 层强制租户隔离。
    # 见 docs/review/01-backend.md S4。通过外键到 prompts 并回填 tenant_id，
    # 使租户过滤可下推到查询层，降低对 Service 层手工过滤的依赖。
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # variables extracted from content: ["var1", "var2", ...]
    variables: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, server_default=func.now())
