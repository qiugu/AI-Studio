from typing import List, Optional
from datetime import datetime

from sqlalchemy.orm import mapped_column, Mapped, relationship
from sqlalchemy import Boolean, String, DateTime, func

from app.core.database import Base
from app.models.role_permission import role_permission

import uuid


class Permission(Base):
    __tablename__ = 'permissions'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    resource: Mapped[str] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(100))
    description: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    scope: Mapped[str] = mapped_column(
        String(20), nullable=False, default="tenant", server_default="tenant"
    )
    sensitivity: Mapped[str] = mapped_column(
        String(20), nullable=False, default="normal", server_default="normal"
    )
    is_delegable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )

    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, server_default=func.now())

    roles: Mapped[List['Role']] = relationship('Role', secondary=role_permission, back_populates="permissions")
