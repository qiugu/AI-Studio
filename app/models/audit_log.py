from typing import Optional
from datetime import datetime

from sqlalchemy.orm import mapped_column, Mapped
from sqlalchemy import String, DateTime, Integer, func

from app.core.database import Base

import uuid


class AuditLog(Base):
    """审计日志模型：记录租户内的写操作（POST/PUT/PATCH/DELETE）。"""

    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)

    # 操作者
    user_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)

    # 操作描述
    action: Mapped[str] = mapped_column(String(20), nullable=False)  # POST/PUT/PATCH/DELETE
    resource: Mapped[str] = mapped_column(String(100), nullable=False, index=True)  # 资源类型，如 ai-models
    resource_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)

    # 请求信息
    method: Mapped[str] = mapped_column(String(10), nullable=False)
    path: Mapped[str] = mapped_column(String(500), nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    ip_address: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
