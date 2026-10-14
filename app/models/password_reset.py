from datetime import datetime
from typing import Optional

import uuid
from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class PasswordResetToken(Base):
    """一次性密码重置令牌；数据库只保存令牌哈希。"""

    __tablename__ = "password_reset_tokens"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    requested_by: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, server_default=func.now()
    )
