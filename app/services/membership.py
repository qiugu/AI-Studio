"""Compatibility dual-write helpers for the staged tenant membership cutover."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import config
from app.models.membership_role import membership_role
from app.models.role import Role
from app.models.tenant import Tenant
from app.models.tenant_membership import TenantMembership
from app.models.user import User
from app.models.user_role import user_role


def _enabled() -> bool:
    return bool(getattr(config, "membership_dual_write_enabled", False))


def membership_readiness_report(db: Session) -> dict[str, Any]:
    """Compare the legacy and staged role graphs before a read cutover.

    The report is intentionally read-only and JSON-serializable so the same
    gate can be used by the migration verifier, a deployment check, or an
    operator dry-run.  Platform identities are excluded because they are
    denied tenant RBAC by the PDP and do not participate in this cutover.
    """
    active_users = (
        db.query(User)
        .filter(
            User.status.is_(True),
            User.deleted_at.is_(None),
            User.is_platform_admin.is_(False),
        )
        .all()
    )
    missing_memberships: list[dict[str, str]] = []
    memberships_without_roles: list[dict[str, str]] = []
    role_set_mismatches: list[dict[str, Any]] = []
    owner_membership_mismatches: list[dict[str, Any]] = []

    for user in active_users:
        membership = (
            db.query(TenantMembership)
            .filter(
                TenantMembership.user_id == user.id,
                TenantMembership.tenant_id == user.tenant_id,
                TenantMembership.status.is_(True),
            )
            .first()
        )
        if membership is None:
            missing_memberships.append(
                {"user_id": str(user.id), "tenant_id": str(user.tenant_id)}
            )
            continue

        legacy_role_ids = {
            str(role_id)
            for (role_id,) in db.query(user_role.c.role_id)
            .join(Role, Role.id == user_role.c.role_id)
            .filter(
                user_role.c.user_id == user.id,
                Role.tenant_id == user.tenant_id,
            )
            .all()
        }
        staged_role_ids = {
            str(role_id)
            for (role_id,) in db.query(membership_role.c.role_id)
            .join(Role, Role.id == membership_role.c.role_id)
            .filter(
                membership_role.c.membership_id == membership.id,
                Role.tenant_id == user.tenant_id,
            )
            .all()
        }
        if not staged_role_ids:
            memberships_without_roles.append(
                {
                    "membership_id": str(membership.id),
                    "user_id": str(user.id),
                    "tenant_id": str(user.tenant_id),
                }
            )
        if legacy_role_ids != staged_role_ids:
            role_set_mismatches.append(
                {
                    "user_id": str(user.id),
                    "tenant_id": str(user.tenant_id),
                    "legacy_role_ids": sorted(legacy_role_ids),
                    "membership_role_ids": sorted(staged_role_ids),
                }
            )

    for tenant in db.query(Tenant).all():
        if tenant.owner_id is None:
            continue
        owner_memberships = (
            db.query(TenantMembership)
            .filter(
                TenantMembership.tenant_id == tenant.id,
                TenantMembership.user_id == tenant.owner_id,
                TenantMembership.status.is_(True),
                TenantMembership.is_owner.is_(True),
            )
            .count()
        )
        active_owner_flags = (
            db.query(TenantMembership)
            .filter(
                TenantMembership.tenant_id == tenant.id,
                TenantMembership.status.is_(True),
                TenantMembership.is_owner.is_(True),
            )
            .count()
        )
        if owner_memberships != 1 or active_owner_flags != 1:
            owner_membership_mismatches.append(
                {
                    "tenant_id": str(tenant.id),
                    "owner_id": str(tenant.owner_id),
                    "matching_owner_memberships": owner_memberships,
                    "active_owner_flags": active_owner_flags,
                }
            )

    membership_user_tenant_mismatches = [
        {
            "membership_id": str(membership.id),
            "membership_tenant_id": str(membership.tenant_id),
            "user_id": str(user.id),
            "user_tenant_id": str(user.tenant_id),
        }
        for membership, user in db.query(TenantMembership, User)
        .join(User, User.id == TenantMembership.user_id)
        .filter(TenantMembership.tenant_id != User.tenant_id)
        .all()
    ]

    invalid_role_bindings = db.execute(
        select(
            membership_role.c.membership_id,
            membership_role.c.role_id,
            TenantMembership.tenant_id,
            Role.tenant_id,
        )
        .select_from(membership_role)
        .join(
            TenantMembership,
            TenantMembership.id == membership_role.c.membership_id,
        )
        .outerjoin(Role, Role.id == membership_role.c.role_id)
        .where(
            (Role.id.is_(None))
            | (TenantMembership.tenant_id != Role.tenant_id)
        )
    ).all()

    invalid_bindings = [
        {
            "membership_id": str(row[0]),
            "role_id": str(row[1]),
            "membership_tenant_id": str(row[2]),
            "role_tenant_id": str(row[3]) if row[3] is not None else None,
        }
        for row in invalid_role_bindings
    ]
    issues: list[dict[str, Any]] = []
    if missing_memberships:
        issues.append({"kind": "missing_memberships", "items": missing_memberships})
    if memberships_without_roles:
        issues.append(
            {
                "kind": "memberships_without_roles",
                "items": memberships_without_roles,
            }
        )
    if role_set_mismatches:
        issues.append(
            {"kind": "role_set_mismatch", "items": role_set_mismatches}
        )
    if owner_membership_mismatches:
        issues.append(
            {
                "kind": "owner_membership_mismatch",
                "items": owner_membership_mismatches,
            }
        )
    if membership_user_tenant_mismatches:
        issues.append(
            {
                "kind": "membership_user_tenant_mismatch",
                "items": membership_user_tenant_mismatches,
            }
        )
    if invalid_bindings:
        issues.append(
            {"kind": "invalid_membership_role_binding", "items": invalid_bindings}
        )

    return {
        "ready": not issues,
        "checked_users": len(active_users),
        "active_memberships": db.query(TenantMembership)
        .filter(TenantMembership.status.is_(True))
        .count(),
        "missing_memberships": missing_memberships,
        "memberships_without_roles": memberships_without_roles,
        "role_set_mismatches": role_set_mismatches,
        "owner_membership_mismatches": owner_membership_mismatches,
        "membership_user_tenant_mismatches": membership_user_tenant_mismatches,
        "invalid_membership_role_bindings": invalid_bindings,
        "issues": issues,
    }


def ensure_membership(
    user_id: str,
    tenant_id: str,
    db: Session,
    *,
    status: bool = True,
    is_owner: bool = False,
) -> TenantMembership | None:
    """Create or repair the additive membership row when dual-write is enabled."""
    if not _enabled():
        return None

    membership = (
        db.query(TenantMembership)
        .filter(
            TenantMembership.user_id == user_id,
            TenantMembership.tenant_id == tenant_id,
        )
        .first()
    )
    if membership is None:
        membership = TenantMembership(
            user_id=user_id,
            tenant_id=tenant_id,
            status=status,
            is_owner=is_owner,
            authz_version=1,
        )
        db.add(membership)
        db.flush()
    else:
        membership.status = status
        membership.is_owner = is_owner
        membership.removed_at = None if status else membership.removed_at
        membership.authz_version = int(membership.authz_version or 1) + 1
    return membership


def sync_membership_roles(
    user_id: str,
    tenant_id: str,
    db: Session,
    *,
    role_ids: Iterable[str] | None = None,
) -> TenantMembership | None:
    """Mirror the current legacy role set into ``membership_roles``."""
    membership = ensure_membership(user_id, tenant_id, db)
    if membership is None:
        return None

    if role_ids is None:
        role_ids = (
            role_id
            for (role_id,) in db.query(user_role.c.role_id)
            .join(Role, Role.id == user_role.c.role_id)
            .filter(
                user_role.c.user_id == user_id,
                Role.tenant_id == tenant_id,
            )
            .all()
        )
    role_ids = set(role_ids)
    db.execute(
        membership_role.delete().where(membership_role.c.membership_id == membership.id)
    )
    for role_id in role_ids:
        db.execute(
            membership_role.insert().values(
                membership_id=membership.id,
                role_id=role_id,
            )
        )
    membership.authz_version = int(membership.authz_version or 1) + 1
    db.flush()
    return membership


def deactivate_membership(user_id: str, tenant_id: str, db: Session) -> None:
    """Retain membership history while making the staged subject inactive."""
    membership = ensure_membership(user_id, tenant_id, db, status=False)
    if membership is None:
        return
    membership.removed_at = datetime.now(timezone.utc)
    db.execute(
        membership_role.delete().where(membership_role.c.membership_id == membership.id)
    )
    membership.authz_version = int(membership.authz_version or 1) + 1
    db.flush()


def sync_membership_owner(
    tenant_id: str,
    previous_owner_id: str | None,
    new_owner_id: str,
    db: Session,
) -> None:
    if not _enabled():
        return
    if previous_owner_id and previous_owner_id != new_owner_id:
        previous = ensure_membership(
            previous_owner_id, tenant_id, db, status=True, is_owner=False
        )
        if previous is not None:
            previous.authz_version = int(previous.authz_version or 1) + 1
    current = ensure_membership(new_owner_id, tenant_id, db, status=True, is_owner=True)
    if current is not None:
        current.authz_version = int(current.authz_version or 1) + 1
