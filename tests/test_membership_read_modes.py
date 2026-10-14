import logging

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core import config as config_module
from app.core.authorization import AuthorizationService, clear_authorization_cache
from app.core.database import Base
from app.core.dependencies import require_tenant_user
from app.core.exceptions import ForbiddenException
from app.models import (
    Permission,
    ResourceGrant,
    Role,
    Tenant,
    TenantMembership,
    User,
)
from app.models.membership_role import membership_role
from app.models.role_permission import role_permission
from app.models.user_role import user_role
from app.services.resource_authorization import ResourceAuthorizationService
from app.services.membership import membership_readiness_report
from app.services.role import set_role_permissions
from app.services.user import build_user_payload


def _db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _fixture(db: Session) -> tuple[Tenant, User, Role, Permission, TenantMembership]:
    tenant = Tenant(id="mode-tenant", name="Mode Tenant")
    actor = User(
        id="mode-user",
        tenant_id=tenant.id,
        email="mode@example.com",
        password_hash="hashed",
        status=True,
        email_verified=True,
    )
    role = Role(
        id="mode-role",
        tenant_id=tenant.id,
        name="Mode Role",
        code="mode-role",
        status=True,
    )
    permission = Permission(
        id="mode-permission",
        resource="agent",
        action="read",
        description="Read agents",
    )
    membership = TenantMembership(
        id="mode-membership",
        tenant_id=tenant.id,
        user_id=actor.id,
        status=True,
    )
    role.permissions.append(permission)
    db.add_all([tenant, actor, role, membership])
    db.flush()
    return tenant, actor, role, permission, membership


def test_shadow_mode_keeps_legacy_enforcement_and_logs_mismatch(monkeypatch, caplog):
    monkeypatch.setattr(config_module.config, "membership_read_mode", "shadow")
    monkeypatch.setattr(config_module.config, "membership_dual_write_enabled", True)
    clear_authorization_cache()
    with _db() as db:
        tenant, actor, role, _permission, _membership = _fixture(db)
        db.execute(user_role.insert().values(user_id=actor.id, role_id=role.id))
        db.commit()

        with caplog.at_level(logging.WARNING, logger="app.core.authorization"):
            decision = AuthorizationService(db).check_permission(
                actor, tenant.id, "agent", "read"
            )

        assert decision.allowed is True
        assert "membership shadow mismatch" in caplog.text
        mismatch = next(
            record
            for record in caplog.records
            if record.message == "authorization membership shadow mismatch"
        )
        assert mismatch.shadow_match is False
        assert mismatch.legacy_decision == {
            "allowed": True,
            "reason": "role_permission_granted",
        }
        assert mismatch.membership_decision == {
            "allowed": False,
            "reason": "membership_role_permission_missing",
        }


def test_shadow_mode_logs_matching_legacy_and_membership_decisions(
    monkeypatch, caplog
):
    monkeypatch.setattr(config_module.config, "membership_read_mode", "shadow")
    monkeypatch.setattr(config_module.config, "membership_dual_write_enabled", True)
    clear_authorization_cache()
    with _db() as db:
        tenant, actor, role, permission, membership = _fixture(db)
        db.execute(user_role.insert().values(user_id=actor.id, role_id=role.id))
        db.execute(
            membership_role.insert().values(
                membership_id=membership.id,
                role_id=role.id,
            )
        )
        db.commit()

        with caplog.at_level(logging.INFO, logger="app.core.authorization"):
            decision = AuthorizationService(db).check_permission(
                actor, tenant.id, permission.resource, permission.action
            )

        assert decision.allowed is True
        match = next(
            record
            for record in caplog.records
            if record.message == "authorization membership shadow decision"
        )
        assert match.shadow_match is True
        assert match.legacy_decision["allowed"] is True
        assert match.membership_decision["allowed"] is True


def test_membership_mode_uses_active_membership_roles(monkeypatch):
    monkeypatch.setattr(config_module.config, "membership_read_mode", "membership")
    monkeypatch.setattr(config_module.config, "membership_dual_write_enabled", True)
    clear_authorization_cache()
    with _db() as db:
        tenant, actor, role, permission, membership = _fixture(db)
        db.execute(
            membership_role.insert().values(
                membership_id=membership.id,
                role_id=role.id,
            )
        )
        db.commit()

        decision = AuthorizationService(db).check_permission(
            actor, tenant.id, permission.resource, permission.action
        )
        assert decision.allowed is True
        assert decision.reason == "membership_role_permission_granted"

        membership.status = False
        db.commit()
        decision = AuthorizationService(db).check_permission(
            actor, tenant.id, permission.resource, permission.action
        )
        assert decision.allowed is False


def test_membership_mode_requires_dual_write_rollout_flag(monkeypatch):
    monkeypatch.setattr(config_module.config, "membership_read_mode", "membership")
    monkeypatch.setattr(config_module.config, "membership_dual_write_enabled", False)
    clear_authorization_cache()
    with _db() as db:
        tenant, actor, role, permission, membership = _fixture(db)
        db.execute(
            membership_role.insert().values(
                membership_id=membership.id,
                role_id=role.id,
            )
        )
        db.commit()

        decision = AuthorizationService(db).check_permission(
            actor, tenant.id, permission.resource, permission.action
        )

        assert decision.allowed is False
        assert decision.reason == "membership_cutover_requires_dual_write"


def test_shadow_mode_requires_dual_write_rollout_flag(monkeypatch):
    monkeypatch.setattr(config_module.config, "membership_read_mode", "shadow")
    monkeypatch.setattr(config_module.config, "membership_dual_write_enabled", False)
    clear_authorization_cache()
    with _db() as db:
        tenant, actor, _role, _permission, _membership = _fixture(db)

        decision = AuthorizationService(db).check_permission(
            actor, tenant.id, "agent", "read"
        )

        assert decision.allowed is False
        assert decision.reason == "membership_cutover_requires_dual_write"


def test_tenant_guard_rejects_membership_mode_before_dual_write(monkeypatch):
    monkeypatch.setattr(config_module.config, "membership_read_mode", "membership")
    monkeypatch.setattr(config_module.config, "membership_dual_write_enabled", False)
    with _db() as db:
        tenant, actor, role, _permission, membership = _fixture(db)
        db.execute(
            membership_role.insert().values(
                membership_id=membership.id,
                role_id=role.id,
            )
        )
        db.commit()

        with pytest.raises(ForbiddenException):
            require_tenant_user(actor, db)


def test_tenant_guard_rejects_shadow_mode_before_dual_write(monkeypatch):
    monkeypatch.setattr(config_module.config, "membership_read_mode", "shadow")
    monkeypatch.setattr(config_module.config, "membership_dual_write_enabled", False)
    with _db() as db:
        tenant, actor, role, _permission, _membership = _fixture(db)
        db.execute(user_role.insert().values(user_id=actor.id, role_id=role.id))
        db.commit()

        with pytest.raises(ForbiddenException):
            require_tenant_user(actor, db)


def test_membership_mode_routes_and_resource_grants_use_membership_roles(monkeypatch):
    monkeypatch.setattr(config_module.config, "membership_read_mode", "membership")
    monkeypatch.setattr(config_module.config, "membership_dual_write_enabled", True)
    with _db() as db:
        tenant, actor, role, _permission, membership = _fixture(db)
        db.execute(
            membership_role.insert().values(
                membership_id=membership.id,
                role_id=role.id,
            )
        )
        db.add(
            ResourceGrant(
                tenant_id=tenant.id,
                resource_type="agent",
                resource_id="agent-1",
                subject_type="role",
                subject_id=role.id,
                actions=["read"],
                created_by=actor.id,
            )
        )
        db.commit()

        assert require_tenant_user(actor, db) is actor
        assert ResourceAuthorizationService(db)._has_active_grant(
            actor, tenant.id, "agent", "agent-1", "read"
        )


def test_membership_mode_capability_snapshot_uses_staged_roles(monkeypatch):
    monkeypatch.setattr(config_module.config, "membership_read_mode", "membership")
    monkeypatch.setattr(config_module.config, "membership_dual_write_enabled", True)
    with _db() as db:
        tenant, actor, legacy_role, legacy_permission, membership = _fixture(db)
        staged_role = Role(
            id="mode-staged-role",
            tenant_id=tenant.id,
            name="Staged Role",
            code="mode-staged-role",
            status=True,
        )
        staged_permission = Permission(
            id="mode-staged-permission",
            resource="workflow",
            action="execute",
            description="Execute workflows",
        )
        staged_role.permissions.append(staged_permission)
        db.add(staged_role)
        db.flush()
        db.execute(user_role.insert().values(user_id=actor.id, role_id=legacy_role.id))
        db.execute(
            membership_role.insert().values(
                membership_id=membership.id,
                role_id=staged_role.id,
            )
        )
        db.commit()

        payload = build_user_payload(actor, db)

        assert "workflow.execute" in payload["capabilities"]
        assert f"{legacy_permission.resource}.{legacy_permission.action}" not in payload[
            "capabilities"
        ]
        assert [role["id"] for role in payload["roles"]] == [staged_role.id]


def test_membership_role_permission_mutation_bumps_membership_version(monkeypatch):
    monkeypatch.setattr(config_module.config, "membership_read_mode", "membership")
    monkeypatch.setattr(config_module.config, "membership_dual_write_enabled", True)
    with _db() as db:
        tenant, actor, role, permission, membership = _fixture(db)
        db.execute(
            membership_role.insert().values(
                membership_id=membership.id,
                role_id=role.id,
            )
        )
        db.commit()

        assert AuthorizationService(db).check_permission(
            actor, tenant.id, permission.resource, permission.action
        ).allowed
        old_membership_version = membership.authz_version
        old_user_version = actor.authz_version

        # Simulate the future cutover where the staged graph is authoritative;
        # no user_roles row is required for the invalidation to be correct.
        set_role_permissions(role.id, [], tenant.id, db)
        db.commit()
        db.refresh(membership)
        db.refresh(actor)

        assert membership.authz_version > old_membership_version
        assert actor.authz_version == old_user_version
        assert not AuthorizationService(db).check_permission(
            actor, tenant.id, permission.resource, permission.action
        ).allowed


def test_invalid_membership_mode_fails_closed(monkeypatch):
    monkeypatch.setattr(config_module.config, "membership_read_mode", "unknown")
    with _db() as db:
        tenant, actor, _role, _permission, _membership = _fixture(db)
        decision = AuthorizationService(db).check_permission(
            actor, tenant.id, "agent", "read"
        )
        assert decision.allowed is False
        assert decision.reason == "invalid_membership_read_mode"


def test_membership_readiness_requires_legacy_and_staged_role_sets_to_match():
    with _db() as db:
        tenant, actor, role, _permission, membership = _fixture(db)
        db.execute(user_role.insert().values(user_id=actor.id, role_id=role.id))
        db.execute(
            membership_role.insert().values(
                membership_id=membership.id,
                role_id=role.id,
            )
        )
        db.commit()

        ready = membership_readiness_report(db)
        assert ready["ready"] is True
        assert ready["checked_users"] == 1
        assert ready["issues"] == []

        db.execute(
            membership_role.delete().where(
                membership_role.c.membership_id == membership.id
            )
        )
        db.commit()
        not_ready = membership_readiness_report(db)
        assert not_ready["ready"] is False
        assert not_ready["memberships_without_roles"] == [
            {
                "membership_id": membership.id,
                "user_id": actor.id,
                "tenant_id": tenant.id,
            }
        ]
        assert any(
            issue["kind"] == "memberships_without_roles"
            for issue in not_ready["issues"]
        )


def test_membership_readiness_rejects_owner_and_user_tenant_drift():
    with _db() as db:
        tenant, actor, _role, _permission, _membership = _fixture(db)
        tenant.owner_id = actor.id
        db.flush()

        mismatched_tenant = Tenant(id="mode-other-tenant", name="Other Tenant")
        mismatched_membership = TenantMembership(
            id="mode-mismatched-membership",
            tenant_id=mismatched_tenant.id,
            user_id=actor.id,
            status=True,
            is_owner=True,
        )
        db.add_all([mismatched_tenant, mismatched_membership])
        db.commit()

        report = membership_readiness_report(db)

        assert report["ready"] is False
        assert report["owner_membership_mismatches"]
        assert report["membership_user_tenant_mismatches"]
