from typing import Optional
from datetime import datetime

from sqlalchemy.orm import mapped_column, Mapped
from sqlalchemy import String, DateTime, Boolean, Integer, ForeignKey, func

from app.core.database import Base

import uuid


class Tenant(Base):
    __tablename__ = 'tenants'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    plan: Mapped[str] = mapped_column(String(50), default="free")
    max_users: Mapped[int] = mapped_column(Integer, default=10)
    max_models: Mapped[int] = mapped_column(Integer, default=5)
    status: Mapped[bool] = mapped_column(Boolean, default=True)
    is_system_init: Mapped[bool] = mapped_column(Boolean, default=False)
    # 租户所有者（创建者）。管理权由 owner_id 推导，与「被显式提升的 admin 角色」解耦。
    owner_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey('users.id'), nullable=True, index=True
    )

    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
