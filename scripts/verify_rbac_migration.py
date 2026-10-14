"""Read-only verification for RBAC and authorization migration state.

The command is intended for a sanitized pre-production copy.  It never writes
data or changes tenant scope.  Use ``--strict`` in a deployment gate to fail
on structural/relational anomalies; users without roles are reported as
inventory because platform bootstrap and staged membership migration may
temporarily contain such rows.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import func, inspect, select
from sqlalchemy.orm import Session

# ``python scripts/verify_rbac_migration.py`` sets ``sys.path[0]`` to the
# scripts directory rather than the repository root.  Add the project root
# explicitly so the documented operator command works without PYTHONPATH.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.models import (
    AuditLog,
    AuthorizationOutbox,
    Permission,
    ResourceGrant,
    Role,
    Tenant,
    TenantMembership,
    User,
    membership_role,
    role_permission,
    user_role,
)
from app.services.membership import membership_readiness_report


REQUIRED_TABLES = {
    "tenants",
    "users",
    "roles",
    "permissions",
    "user_roles",
    "role_permissions",
    "resource_grants",
    "audit_logs",
    "authorization_outbox",
    "tenant_memberships",
    "membership_roles",
}


def _table_names(db: Session) -> set[str]:
    bind = db.get_bind()
    return set(inspect(bind).get_table_names())


def _missing_model_columns(db: Session, tables: set[str]) -> dict[str, list[str]]:
    """Find ORM columns absent from an older schema before issuing ORM SQL."""
    expected_models = (Tenant, User, Role, Permission)
    inspector = inspect(db.get_bind())
    missing: dict[str, list[str]] = {}
    for model in expected_models:
        table_name = model.__tablename__
        if table_name not in tables:
            continue
        actual_columns = {
            column["name"] for column in inspector.get_columns(table_name)
        }
        expected_columns = {column.name for column in model.__table__.columns}
        absent = sorted(expected_columns - actual_columns)
        if absent:
            missing[table_name] = absent
    return missing


def build_report(db: Session) -> dict[str, Any]:
    """Build a JSON-serializable, non-mutating migration health report."""
    tables = _table_names(db)
    missing_tables = sorted(REQUIRED_TABLES - tables)
    anomalies: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    if missing_tables:
        anomalies.append({"kind": "missing_table", "tables": missing_tables})

    report: dict[str, Any] = {
        "schema": {
            "required_tables": sorted(REQUIRED_TABLES),
            "missing_tables": missing_tables,
        },
        "tenants": {},
        "inventory": {},
        "anomalies": anomalies,
        "warnings": warnings,
    }

    missing_columns = _missing_model_columns(db, tables)
    report["schema"]["missing_columns"] = missing_columns
    if missing_columns:
        anomalies.append({
            "kind": "missing_column",
            "columns": missing_columns,
        })
        report["summary"] = {
            "tenant_count": 0,
            "anomaly_count": len(anomalies),
            "warning_count": len(warnings),
        }
        return report

    # The remaining checks require the base identity/role tables.  Returning
    # the schema failure is more useful than raising a secondary SQL error.
    if not {"tenants", "users", "roles", "permissions"} <= tables:
        return report

    tenant_ids = [tenant_id for (tenant_id,) in db.query(Tenant.id).all()]
    for tenant_id in tenant_ids:
        tenant_report: dict[str, Any] = {
            "users": db.query(User).filter(User.tenant_id == tenant_id).count(),
            "active_users": db.query(User).filter(
                User.tenant_id == tenant_id,
                User.status.is_(True),
                User.deleted_at.is_(None),
            ).count(),
            "roles": db.query(Role).filter(Role.tenant_id == tenant_id).count(),
        }
        if "user_roles" in tables:
            tenant_report["role_assignments"] = db.execute(
                select(func.count())
                .select_from(user_role)
                .join(User, User.id == user_role.c.user_id)
                .join(Role, Role.id == user_role.c.role_id)
                .where(User.tenant_id == tenant_id, Role.tenant_id == tenant_id)
            ).scalar_one()
        if "resource_grants" in tables:
            tenant_report["resource_grants"] = db.query(ResourceGrant).filter(
                ResourceGrant.tenant_id == tenant_id
            ).count()
        if "audit_logs" in tables:
            tenant_report["audit_logs"] = db.query(AuditLog).filter(
                AuditLog.tenant_id == tenant_id
            ).count()
        if "authorization_outbox" in tables:
            tenant_report["authorization_outbox"] = db.query(
                AuthorizationOutbox
            ).filter(AuthorizationOutbox.tenant_id == tenant_id).count()
        if "tenant_memberships" in tables:
            tenant_report["memberships"] = db.query(TenantMembership).filter(
                TenantMembership.tenant_id == tenant_id
            ).count()
        if "membership_roles" in tables:
            tenant_report["membership_role_assignments"] = db.execute(
                select(func.count())
                .select_from(membership_role)
                .join(
                    TenantMembership,
                    TenantMembership.id == membership_role.c.membership_id,
                )
                .join(Role, Role.id == membership_role.c.role_id)
                .where(
                    TenantMembership.tenant_id == tenant_id,
                    Role.tenant_id == tenant_id,
                )
            ).scalar_one()
        report["tenants"][tenant_id] = tenant_report

    if "user_roles" in tables:
        orphan_user_roles = db.execute(
            select(user_role.c.user_id, user_role.c.role_id)
            .outerjoin(User, User.id == user_role.c.user_id)
            .outerjoin(Role, Role.id == user_role.c.role_id)
            .where(User.id.is_(None) | Role.id.is_(None))
        ).all()
        if orphan_user_roles:
            anomalies.append({
                "kind": "orphan_user_role",
                "count": len(orphan_user_roles),
                "sample": [list(row) for row in orphan_user_roles[:20]],
            })

        cross_tenant_user_roles = db.execute(
            select(user_role.c.user_id, user_role.c.role_id, User.tenant_id, Role.tenant_id)
            .join(User, User.id == user_role.c.user_id)
            .join(Role, Role.id == user_role.c.role_id)
            .where(User.tenant_id != Role.tenant_id)
        ).all()
        if cross_tenant_user_roles:
            anomalies.append({
                "kind": "cross_tenant_user_role",
                "count": len(cross_tenant_user_roles),
                "sample": [list(row) for row in cross_tenant_user_roles[:20]],
            })

        users_without_roles = db.execute(
            select(User.id, User.tenant_id)
            .outerjoin(user_role, user_role.c.user_id == User.id)
            .where(
                User.deleted_at.is_(None),
                User.is_platform_admin.is_(False),
                user_role.c.user_id.is_(None),
            )
        ).all()
        if users_without_roles:
            report["inventory"]["users_without_roles"] = [
                {"user_id": row[0], "tenant_id": row[1]}
                for row in users_without_roles
            ]
            warnings.append({
                "kind": "users_without_roles",
                "count": len(users_without_roles),
            })

    if "role_permissions" in tables:
        orphan_role_permissions = db.execute(
            select(role_permission.c.role_id, role_permission.c.permission_id)
            .outerjoin(Role, Role.id == role_permission.c.role_id)
            .outerjoin(Permission, Permission.id == role_permission.c.permission_id)
            .where(Role.id.is_(None) | Permission.id.is_(None))
        ).all()
        if orphan_role_permissions:
            anomalies.append({
                "kind": "orphan_role_permission",
                "count": len(orphan_role_permissions),
                "sample": [list(row) for row in orphan_role_permissions[:20]],
            })

    if {"tenant_memberships", "membership_roles", "user_roles"} <= tables:
        memberships = db.query(TenantMembership).all()
        if memberships:
            membership_by_user = {
                (item.user_id, item.tenant_id): item for item in memberships
            }
            membership_role_rows = db.execute(
                select(
                    TenantMembership.user_id,
                    TenantMembership.tenant_id,
                    membership_role.c.role_id,
                )
                .select_from(membership_role)
                .join(
                    TenantMembership,
                    TenantMembership.id == membership_role.c.membership_id,
                )
            ).all()
            staged_roles: dict[tuple[str, str], set[str]] = {}
            for user_id, tenant_id, role_id in membership_role_rows:
                staged_roles.setdefault((user_id, tenant_id), set()).add(role_id)

            memberships_without_roles = (
                db.query(TenantMembership)
                .outerjoin(
                    membership_role,
                    membership_role.c.membership_id == TenantMembership.id,
                )
                .filter(
                    TenantMembership.status.is_(True),
                    membership_role.c.membership_id.is_(None),
                )
                .all()
            )
            if memberships_without_roles:
                report["inventory"]["memberships_without_roles"] = [
                    {
                        "membership_id": membership.id,
                        "user_id": membership.user_id,
                        "tenant_id": membership.tenant_id,
                    }
                    for membership in memberships_without_roles
                ]
                warnings.append({
                    "kind": "memberships_without_roles",
                    "count": len(memberships_without_roles),
                })

            mismatches: list[dict[str, Any]] = []
            for user in db.query(User).filter(User.deleted_at.is_(None)).all():
                key = (user.id, user.tenant_id)
                if key not in membership_by_user:
                    mismatches.append(
                        {"user_id": user.id, "tenant_id": user.tenant_id, "kind": "missing"}
                    )
                    continue
                legacy_roles = {
                    role_id
                    for (role_id,) in db.query(user_role.c.role_id)
                    .filter(user_role.c.user_id == user.id)
                    .all()
                }
                if legacy_roles != staged_roles.get(key, set()):
                    mismatches.append(
                        {
                            "user_id": user.id,
                            "tenant_id": user.tenant_id,
                            "kind": "role_set_mismatch",
                            "legacy_count": len(legacy_roles),
                            "membership_count": len(staged_roles.get(key, set())),
                        }
                    )
            if mismatches:
                anomalies.append({
                    "kind": "membership_legacy_mismatch",
                    "count": len(mismatches),
                    "sample": mismatches[:20],
                })

        # The same read-only comparison is exposed as a cutover gate.  Keep
        # it separate from the inventory above so operators can consume one
        # stable result before changing ``MEMBERSHIP_READ_MODE``.
        if db.query(TenantMembership).count():
            readiness = membership_readiness_report(db)
            report["membership_readiness"] = readiness
            if not readiness["ready"]:
                anomalies.append({
                    "kind": "membership_cutover_not_ready",
                    "count": len(readiness["issues"]),
                    "sample": readiness["issues"][:20],
                })

    duplicate_permissions = db.execute(
        select(
            Permission.resource,
            Permission.action,
            func.count(Permission.id),
        )
        .group_by(Permission.resource, Permission.action)
        .having(func.count(Permission.id) > 1)
    ).all()
    if duplicate_permissions:
        anomalies.append({
            "kind": "duplicate_permission_key",
            "count": len(duplicate_permissions),
            "sample": [list(row) for row in duplicate_permissions[:20]],
        })

    permission_columns = {
        column["name"] for column in inspect(db.get_bind()).get_columns("permissions")
    }
    if {"scope", "sensitivity", "is_delegable"} <= permission_columns:
        invalid_metadata = db.query(Permission).all()
        invalid_metadata = [
            permission
            for permission in invalid_metadata
            if permission.scope not in {"tenant", "platform"}
            or permission.sensitivity not in {"normal", "high", "critical"}
            or (permission.scope == "platform" and permission.is_delegable)
        ]
        if invalid_metadata:
            anomalies.append({
                "kind": "invalid_permission_metadata",
                "count": len(invalid_metadata),
                "sample": [
                    {
                        "permission_id": permission.id,
                        "resource": permission.resource,
                        "action": permission.action,
                        "scope": permission.scope,
                        "sensitivity": permission.sensitivity,
                        "is_delegable": permission.is_delegable,
                    }
                    for permission in invalid_metadata[:20]
                ],
            })

    if "resource_grants" in tables:
        invalid_grants = db.execute(
            select(ResourceGrant.id, ResourceGrant.tenant_id, Role.tenant_id)
            .join(
                Role,
                (Role.id == ResourceGrant.subject_id)
                & (ResourceGrant.subject_type == "role"),
                isouter=True,
            )
            .where(
                ResourceGrant.subject_type == "role",
                (Role.id.is_(None) | (Role.tenant_id != ResourceGrant.tenant_id)),
            )
        ).all()
        if invalid_grants:
            anomalies.append({
                "kind": "invalid_resource_grant_subject",
                "count": len(invalid_grants),
                "sample": [list(row) for row in invalid_grants[:20]],
            })

    if "authorization_outbox" in tables:
        invalid_outbox = db.query(AuthorizationOutbox).filter(
            AuthorizationOutbox.status.not_in({"pending", "processing", "failed", "processed"})
        ).count()
        if invalid_outbox:
            anomalies.append({
                "kind": "invalid_authorization_outbox_status",
                "count": invalid_outbox,
            })

    report["summary"] = {
        "tenant_count": len(tenant_ids),
        "anomaly_count": len(anomalies),
        "warning_count": len(warnings),
    }
    return report


def membership_cutover_ready(report: dict[str, Any]) -> bool:
    """Return whether the staged membership graph is safe to read from.

    This is deliberately stricter than merely finding the membership tables:
    a deployment gate must have a readiness report, no role-graph drift, and
    no structural/relational anomalies before ``MEMBERSHIP_READ_MODE`` can be
    changed from ``legacy``/``shadow`` to ``membership``.
    """
    readiness = report.get("membership_readiness")
    return bool(
        readiness
        and readiness.get("ready") is True
        and not report.get("anomalies")
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="return non-zero when structural or relational anomalies exist",
    )
    parser.add_argument(
        "--require-membership-ready",
        action="store_true",
        help=(
            "return non-zero unless membership_readiness.ready is true and "
            "the report has no anomalies"
        ),
    )
    args = parser.parse_args()

    from app.core.database import sessionLocal
    from app.core.tenant_scope import tenant_scope_context

    db = sessionLocal()
    try:
        # This is an intentional cross-tenant maintenance read; make the
        # platform context explicit instead of relying on an absent scope.
        with tenant_scope_context(
            "migration-verifier",
            is_platform_admin=True,
            allow_cross_tenant=True,
        ):
            report = build_report(db)
    finally:
        db.close()

    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    strict_failed = args.strict and bool(report["anomalies"])
    membership_gate_failed = (
        args.require_membership_ready and not membership_cutover_ready(report)
    )
    return 1 if strict_failed or membership_gate_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
