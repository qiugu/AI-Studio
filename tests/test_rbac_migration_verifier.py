import importlib.util
import os
from pathlib import Path
import subprocess
import sys

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Permission, Role, Tenant, TenantMembership, User
from app.models.role_permission import role_permission
from app.models.user_role import user_role


def _load_verifier():
    path = Path(__file__).parents[1] / "scripts" / "verify_rbac_migration.py"
    spec = importlib.util.spec_from_file_location("verify_rbac_migration", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_verifier_cli_entrypoint_resolves_project_imports():
    script = Path(__file__).parents[1] / "scripts" / "verify_rbac_migration.py"
    environment = os.environ.copy()
    environment["AI_STUDIO_SKIP_ENV_FILE"] = "1"

    result = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=script.parents[1],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "--require-membership-ready" in result.stdout


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_verifier_reports_clean_tenant_role_inventory(db):
    tenant = Tenant(id="verify-tenant", name="Verify Tenant")
    role = Role(
        id="verify-role",
        tenant_id=tenant.id,
        name="Member",
        code="verify-member",
        status=True,
    )
    permission = Permission(
        id="verify-permission",
        resource="agent",
        action="read",
        description="Read agents",
    )
    user = User(
        id="verify-user",
        tenant_id=tenant.id,
        email="verify@example.com",
        password_hash="hashed",
        status=True,
        email_verified=True,
    )
    role.permissions.append(permission)
    user.roles.append(role)
    db.add_all([tenant, user])
    db.commit()

    report = _load_verifier().build_report(db)

    assert report["summary"] == {
        "tenant_count": 1,
        "anomaly_count": 0,
        "warning_count": 0,
    }
    assert report["tenants"][tenant.id]["users"] == 1
    assert report["tenants"][tenant.id]["role_assignments"] == 1


def test_verifier_detects_cross_tenant_role_binding_and_duplicate_permission(db):
    tenant_a = Tenant(id="verify-tenant-a", name="Tenant A")
    tenant_b = Tenant(id="verify-tenant-b", name="Tenant B")
    role = Role(
        id="verify-role-a",
        tenant_id=tenant_a.id,
        name="Role A",
        code="verify-role-a",
        status=True,
    )
    user = User(
        id="verify-user-b",
        tenant_id=tenant_b.id,
        email="verify-b@example.com",
        password_hash="hashed",
        status=True,
        email_verified=True,
    )
    db.add_all([tenant_a, tenant_b, role, user])
    db.flush()
    db.execute(user_role.insert().values(user_id=user.id, role_id=role.id))
    db.add_all(
        [
            Permission(
                id="verify-permission-1",
                resource="agent",
                action="chat",
                description="Chat 1",
            ),
            Permission(
                id="verify-permission-2",
                resource="agent",
                action="chat",
                description="Chat 2",
            ),
        ]
    )
    db.commit()

    report = _load_verifier().build_report(db)
    kinds = {item["kind"] for item in report["anomalies"]}

    assert "cross_tenant_user_role" in kinds
    assert "duplicate_permission_key" in kinds


def test_verifier_detects_membership_role_drift(db):
    tenant = Tenant(id="verify-membership-tenant", name="Membership Tenant")
    role = Role(
        id="verify-membership-role",
        tenant_id=tenant.id,
        name="Member",
        code="verify-membership-role",
        status=True,
    )
    user = User(
        id="verify-membership-user",
        tenant_id=tenant.id,
        email="membership@example.com",
        password_hash="hashed",
        status=True,
        email_verified=True,
    )
    membership = TenantMembership(
        id="verify-membership",
        tenant_id=tenant.id,
        user_id=user.id,
        status=True,
    )
    db.add_all([tenant, role, user, membership])
    db.flush()
    db.execute(user_role.insert().values(user_id=user.id, role_id=role.id))
    db.commit()

    report = _load_verifier().build_report(db)

    assert report["membership_readiness"]["ready"] is False
    assert any(
        item["kind"] == "membership_legacy_mismatch"
        for item in report["anomalies"]
    )


def test_verifier_detects_invalid_permission_metadata(db):
    db.add(
        Permission(
            id="verify-invalid-metadata",
            resource="platform",
            action="bad",
            description="Invalid",
            scope="platform",
            sensitivity="normal",
            is_delegable=True,
        )
    )
    db.commit()

    report = _load_verifier().build_report(db)

    assert any(
        item["kind"] == "invalid_permission_metadata"
        for item in report["anomalies"]
    )


def test_verifier_reports_active_membership_without_staged_roles(db):
    tenant = Tenant(id="verify-no-staged-role-tenant", name="No Staged Role")
    user = User(
        id="verify-no-staged-role-user",
        tenant_id=tenant.id,
        email="no-staged-role@example.com",
        password_hash="hashed",
        status=True,
        email_verified=True,
    )
    membership = TenantMembership(
        id="verify-no-staged-role-membership",
        tenant_id=tenant.id,
        user_id=user.id,
        status=True,
    )
    db.add_all([tenant, user, membership])
    db.commit()

    report = _load_verifier().build_report(db)

    assert report["inventory"]["memberships_without_roles"] == [
        {
            "membership_id": membership.id,
            "user_id": user.id,
            "tenant_id": tenant.id,
        }
    ]
    assert any(
        item["kind"] == "memberships_without_roles"
        for item in report["warnings"]
    )


def test_verifier_reports_missing_columns_before_using_new_orm_model(db):
    # This models a pre-migration database where the base tables exist but
    # newer ORM columns (for example users.email_verified) do not.
    engine = db.get_bind()
    Base.metadata.drop_all(engine)
    legacy_metadata = sa.MetaData()
    sa.Table("tenants", legacy_metadata, sa.Column("id", sa.String(36), primary_key=True))
    sa.Table(
        "users",
        legacy_metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
    )
    sa.Table(
        "roles",
        legacy_metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
    )
    sa.Table(
        "permissions",
        legacy_metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("resource", sa.String(100), nullable=False),
        sa.Column("action", sa.String(100), nullable=False),
    )
    legacy_metadata.create_all(engine)

    report = _load_verifier().build_report(db)

    assert any(item["kind"] == "missing_column" for item in report["anomalies"])
    assert "users" in report["schema"]["missing_columns"]


def test_membership_cutover_gate_requires_ready_report(db):
    verifier = _load_verifier()

    tenant = Tenant(id="verify-gate-tenant", name="Gate Tenant")
    user = User(
        id="verify-gate-user",
        tenant_id=tenant.id,
        email="gate@example.com",
        password_hash="hashed",
        status=True,
        email_verified=True,
    )
    membership = TenantMembership(
        id="verify-gate-membership",
        tenant_id=tenant.id,
        user_id=user.id,
        status=True,
    )
    db.add_all([tenant, user, membership])
    db.commit()

    report = verifier.build_report(db)

    assert verifier.membership_cutover_ready(report) is False


def test_membership_cutover_gate_accepts_clean_legacy_and_staged_graph(db):
    verifier = _load_verifier()

    tenant = Tenant(id="verify-gate-clean-tenant", name="Clean Gate Tenant")
    role = Role(
        id="verify-gate-clean-role",
        tenant_id=tenant.id,
        name="Member",
        code="verify-gate-clean-member",
        status=True,
    )
    user = User(
        id="verify-gate-clean-user",
        tenant_id=tenant.id,
        email="gate-clean@example.com",
        password_hash="hashed",
        status=True,
        email_verified=True,
    )
    membership = TenantMembership(
        id="verify-gate-clean-membership",
        tenant_id=tenant.id,
        user_id=user.id,
        status=True,
    )
    db.add_all([tenant, role, user, membership])
    db.flush()
    db.execute(user_role.insert().values(user_id=user.id, role_id=role.id))
    from app.models.membership_role import membership_role

    db.execute(
        membership_role.insert().values(
            membership_id=membership.id,
            role_id=role.id,
        )
    )
    db.commit()

    report = verifier.build_report(db)

    assert verifier.membership_cutover_ready(report) is True
