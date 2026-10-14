from datetime import datetime
from typing import List, Optional

import uuid
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.membership_role import membership_role


class TenantMembership(Base):
    """User-to-tenant authorization subject used by the staged membership migration.

    ``users.tenant_id`` and ``user_roles`` remain the live authorization source
    until the membership read switch is explicitly enabled.  This model is
    therefore intentionally additive and keeps enough state for a safe cutover.
    """

    __tablename__ = "tenant_memberships"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", name="uq_tenant_membership_user"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    status: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_owner: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    authz_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    joined_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, server_default=func.now()
    )
    removed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    user: Mapped["User"] = relationship("User", back_populates="memberships")
    roles: Mapped[List["Role"]] = relationship(
        "Role", secondary=membership_role, back_populates="memberships"
    )
