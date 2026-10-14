import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.authorization import (
    AuthorizationService,
    clear_authorization_cache,
    get_authorization_decision,
)
from app.core.database import Base
from app.core.exceptions import ForbiddenException, ValidationException
from app.models import Permission, Role, Tenant, User
from app.models.user_role import user_role


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    clear_authorization_cache()
    with Session(engine) as session:
        yield session
    clear_authorization_cache()


def _create_actor(db: Session, tenant_id: str = "tenant-a") -> User:
    tenant = Tenant(id=tenant_id, name=f"Tenant {tenant_id}")
    permission = Permission(resource="agent", action="chat", description="Chat")
    role = Role(
        tenant_id=tenant_id,
        name="Operator",
        code=f"operator-{tenant_id}",
        status=True,
    )
    role.permissions.append(permission)
    actor = User(
        tenant_id=tenant_id,
        email=f"{tenant_id}@example.com",
        password_hash="hashed",
        status=True,
        email_verified=True,
    )
    actor.roles.append(role)
    db.add_all([tenant, actor])
    db.commit()
    db.refresh(actor)
    return actor


def test_permission_is_granted_through_active_tenant_role(db):
    actor = _create_actor(db)

    decision = AuthorizationService(db).check_permission(
        actor, "tenant-a", "agent", "chat"
    )

    assert decision.allowed is True
    assert decision.permission_key == "agent.chat"
    assert get_authorization_decision() == decision


def test_permission_is_denied_for_platform_admin_in_tenant_context(db):
    actor = _create_actor(db)
    actor.is_platform_admin = True
    db.commit()

    decision = AuthorizationService(db).check_permission(
        actor, "tenant-a", "agent", "chat"
    )

    assert decision.allowed is False
    assert decision.reason == "platform_identity_cannot_use_tenant_rbac"


def test_permission_is_denied_when_target_resource_belongs_to_another_tenant(db):
    actor = _create_actor(db)
    other_tenant_resource = type("Resource", (), {"tenant_id": "tenant-b"})()

    decision = AuthorizationService(db).check_permission(
        actor,
        "tenant-a",
        "agent",
        "chat",
        resource_obj=other_tenant_resource,
    )

    assert decision.allowed is False
    assert decision.reason == "resource_tenant_mismatch"


def test_permission_is_denied_when_role_is_disabled(db):
    actor = _create_actor(db)
    actor.roles[0].status = False
    db.commit()

    decision = AuthorizationService(db).check_permission(
        actor, "tenant-a", "agent", "chat"
    )

    assert decision.allowed is False
    assert decision.reason == "role_permission_missing"


def test_permission_is_denied_for_inactive_tenant(db):
    actor = _create_actor(db)
    tenant = db.query(Tenant).filter(Tenant.id == "tenant-a").one()
    tenant.status = False
    db.commit()

    decision = AuthorizationService(db).check_permission(
        actor, "tenant-a", "agent", "chat"
    )

    assert decision.allowed is False
    assert decision.reason == "tenant_inactive"


def test_require_permission_raises_for_denied_decision(db):
    actor = _create_actor(db)

    with pytest.raises(ForbiddenException):
        AuthorizationService(db).require_permission(
            actor, "tenant-a", "agent", "update"
        )


def test_permission_is_denied_when_role_belongs_to_another_tenant(db):
    actor = _create_actor(db, tenant_id="tenant-a")
    other_tenant = Tenant(id="tenant-b", name="Tenant B")
    other_role = Role(
        tenant_id="tenant-b",
        name="Other Operator",
        code="other-operator",
        status=True,
    )
    permission = Permission(resource="agent", action="update", description="Update")
    other_role.permissions.append(permission)
    db.add_all([other_tenant, other_role, permission])
    actor.roles.append(other_role)
    db.commit()

    decision = AuthorizationService(db).check_permission(
        actor, "tenant-a", "agent", "update"
    )

    assert decision.allowed is False
    assert decision.reason == "role_permission_missing"


def test_unknown_permission_fails_closed(db):
    actor = _create_actor(db)

    with pytest.raises(ValidationException):
        AuthorizationService(db).check_permission(
            actor, "tenant-a", "agent", "not_in_catalog"
        )


def test_positive_permission_cache_is_invalidated_by_authz_version(db):
    actor = _create_actor(db)
    service = AuthorizationService(db)

    assert service.check_permission(actor, "tenant-a", "agent", "chat").allowed

    # Simulate a stale cache entry from a mutation path that did not bump the
    # version.  The supported mutation services always bump authz_version.
    db.execute(user_role.delete().where(user_role.c.user_id == actor.id))
    db.commit()
    assert service.check_permission(actor, "tenant-a", "agent", "chat").allowed

    actor.authz_version += 1
    db.commit()
    decision = service.check_permission(actor, "tenant-a", "agent", "chat")
    assert decision.allowed is False
    assert decision.reason == "role_permission_missing"


def test_denied_permission_is_not_cached(db):
    actor = _create_actor(db)
    service = AuthorizationService(db)

    first = service.check_permission(actor, "tenant-a", "agent", "update")
    assert first.allowed is False
    assert first.reason == "permission_not_configured"

    permission = Permission(resource="agent", action="update", description="Update")
    db.add(permission)
    actor.roles[0].permissions.append(permission)
    db.commit()

    second = service.check_permission(actor, "tenant-a", "agent", "update")
    assert second.allowed is True
