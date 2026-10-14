from sqlalchemy import Column, ForeignKey, String, Table

from app.core.database import Base


membership_role = Table(
    "membership_roles",
    Base.metadata,
    Column(
        "membership_id",
        String(36),
        ForeignKey("tenant_memberships.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "role_id",
        String(36),
        ForeignKey("roles.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)
