from typing import List, Optional
from datetime import datetime

from sqlalchemy.orm import mapped_column, Mapped, relationship
from sqlalchemy import String, DateTime, Boolean, ForeignKey, func

from app.core.database import Base
from app.models.role_permission import role_permission
from app.models.user_role import user_role

import uuid


class Role(Base):
    __tablename__ = 'roles'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey('tenants.id'), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100))
    code: Mapped[str] = mapped_column(String(100), unique=True)
    description: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, server_default=func.now())

    permissions: Mapped[List['Permission']] = relationship('Permission', secondary=role_permission, back_populates="roles")
    users: Mapped[List['User']] = relationship('User', secondary=user_role, back_populates="roles")
