"""Explicit role-based sharing grants for tenant resources."""
from datetime import datetime
from typing import List, Optional

import uuid
from sqlalchemy import DateTime, ForeignKey, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ResourceGrant(Base):
    __tablename__ = "resource_grants"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id"), nullable=False, index=True
    )
    resource_type: Mapped[str] = mapped_column(String(50), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    subject_type: Mapped[str] = mapped_column(String(20), nullable=False, default="role")
    subject_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    actions: Mapped[List[str]] = mapped_column(JSON, nullable=False, default=list)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_by: Mapped[str] = mapped_column(String(36), nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, server_default=func.now(), nullable=True
    )
