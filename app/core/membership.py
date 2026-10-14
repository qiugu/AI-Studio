"""Read-path helpers for the staged tenant membership cutover."""

from sqlalchemy import Select, select

from app.core.config import config
from app.models.membership_role import membership_role
from app.models.tenant_membership import TenantMembership
from app.models.user_role import user_role


def membership_read_mode() -> str:
    return str(getattr(config, "membership_read_mode", "legacy")).lower()


def effective_role_ids(user_id: str, tenant_id: str) -> Select:
    """Return the configured authorization role source as a subquery."""
    if membership_read_mode() == "membership":
        return (
            select(membership_role.c.role_id)
            .select_from(membership_role)
            .join(
                TenantMembership,
                TenantMembership.id == membership_role.c.membership_id,
            )
            .where(
                TenantMembership.user_id == user_id,
                TenantMembership.tenant_id == tenant_id,
                TenantMembership.status.is_(True),
            )
        )
    return select(user_role.c.role_id).where(user_role.c.user_id == user_id)
