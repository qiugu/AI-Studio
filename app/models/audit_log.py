from typing import Optional
from datetime import datetime

from sqlalchemy.orm import mapped_column, Mapped
from sqlalchemy import String, DateTime, Integer, JSON, func

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
    user_agent: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    request_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # 授权决策上下文；普通 HTTP 审计记录可为空。
    decision: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    permission_key: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    target_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    target_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column("metadata", JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
