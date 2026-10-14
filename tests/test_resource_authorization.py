from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Permission, Role, Tenant, User
from app.models.resource_grant import ResourceGrant
from app.models.user_role import user_role
from app.services.resource_authorization import (
    ResourceAuthorizationService,
    ResourceGrantService,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _actor(
    db: Session,
    *,
    user_id: str,
    role_id: str,
    email: str,
    actions: set[str],
    permission_resource: str = "agent",
) -> User:
    tenant = db.query(Tenant).filter(Tenant.id == "tenant-resource").one_or_none()
    if tenant is None:
        tenant = Tenant(id="tenant-resource", name="Resource Tenant")
        db.add(tenant)
        db.flush()

    role = Role(
        id=role_id,
        tenant_id=tenant.id,
        name=role_id,
        code=role_id,
        status=True,
    )
    user = User(
        id=user_id,
        tenant_id=tenant.id,
        email=email,
        password_hash="hashed",
        status=True,
        email_verified=True,
    )
    for action in actions:
        permission = (
            db.query(Permission)
            .filter(
                Permission.resource == permission_resource,
                Permission.action == action,
            )
            .one_or_none()
        )
        if permission is None:
            permission = Permission(
                resource=permission_resource,
                action=action,
                description=action,
            )
            db.add(permission)
            db.flush()
        role.permissions.append(permission)
    user.roles.append(role)
    db.add(user)
    db.flush()
    return user


def _resource(*, tenant_id: str = "tenant-resource", created_by: str = "owner"):
    return SimpleNamespace(
        id="agent-1",
        tenant_id=tenant_id,
        created_by=created_by,
        status="draft",
        deleted_at=None,
    )


def test_owner_can_read_own_draft_but_non_owner_cannot(db):
    owner = _actor(
        db,
        user_id="owner",
        role_id="owner-role",
        email="owner@example.com",
        actions={"read"},
    )
    member = _actor(
        db,
        user_id="member",
        role_id="member-role",
        email="member@example.com",
        actions={"read"},
    )
    db.commit()
    resource = _resource(created_by=owner.id)
    service = ResourceAuthorizationService(db)

    owner_decision = service.check(owner, "tenant-resource", "agent", "read", resource)
    member_decision = service.check(member, "tenant-resource", "agent", "read", resource)

    assert owner_decision.allowed is True
    assert owner_decision.reason == "resource_owner_granted"
    assert member_decision.allowed is False
    assert member_decision.reason == "resource_unpublished"


def test_published_resource_is_readable_with_base_permission(db):
    member = _actor(
        db,
        user_id="member",
        role_id="member-role",
        email="member@example.com",
        actions={"read"},
    )
    db.commit()
    resource = _resource(created_by="other")
    resource.status = "published"

    decision = ResourceAuthorizationService(db).check(
        member, "tenant-resource", "agent", "read", resource
    )

    assert decision.allowed is True
    assert decision.reason == "role_permission_granted"


def test_allowed_actions_exposes_effective_resource_actions(db):
    member = _actor(
        db,
        user_id="member",
        role_id="member-role",
        email="member@example.com",
        actions={"read", "update", "execute"},
        permission_resource="agent",
    )
    db.commit()
    resource = _resource(created_by="other")
    resource.status = "published"

    actions = ResourceAuthorizationService(db).allowed_actions(
        member,
        "tenant-resource",
        "agent",
        resource,
    )

    assert actions == ["read", "update"]


def test_resource_manager_can_update_another_users_draft(db):
    owner = _actor(
        db,
        user_id="owner",
        role_id="owner-role",
        email="owner@example.com",
        actions={"read"},
    )
    manager = _actor(
        db,
        user_id="manager",
        role_id="manager-role",
        email="manager@example.com",
        actions={"update"},
    )
    db.commit()

    decision = ResourceAuthorizationService(db).check(
        manager,
        "tenant-resource",
        "agent",
        "update",
        _resource(created_by=owner.id),
    )

    assert decision.allowed is True
    assert decision.reason == "resource_management_granted"


def test_role_grant_allows_declared_action_and_expiry_revokes_it(db):
    owner = _actor(
        db,
        user_id="owner",
        role_id="owner-role",
        email="owner@example.com",
        actions={"read"},
    )
    member = _actor(
        db,
        user_id="member",
        role_id="member-role",
        email="member@example.com",
        actions={"read"},
    )
    resource = _resource(created_by=owner.id)
    db.add(
        ResourceGrant(
            tenant_id="tenant-resource",
            resource_type="agent",
            resource_id=resource.id,
            subject_type="role",
            subject_id="member-role",
            actions=["read"],
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
            created_by=owner.id,
        )
    )
    db.commit()

    service = ResourceAuthorizationService(db)
    granted = service.check(member, "tenant-resource", "agent", "read", resource)
    assert granted.allowed is True
    assert granted.reason == "resource_grant_granted"

    grant = db.query(ResourceGrant).one()
    grant.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()
    expired = service.check(member, "tenant-resource", "agent", "read", resource)
    assert expired.allowed is False
    assert expired.reason == "resource_unpublished"


def test_cross_tenant_and_deleted_resources_are_denied(db):
    member = _actor(
        db,
        user_id="member",
        role_id="member-role",
        email="member@example.com",
        actions={"read"},
    )
    db.commit()
    service = ResourceAuthorizationService(db)

    cross_tenant = service.check(
        member,
        "tenant-resource",
        "agent",
        "read",
        _resource(tenant_id="tenant-other"),
    )
    deleted_resource = _resource()
    deleted_resource.status = "published"
    deleted_resource.deleted_at = datetime.now(timezone.utc)
    deleted = service.check(
        member, "tenant-resource", "agent", "read", deleted_resource
    )

    assert cross_tenant.allowed is False
    assert cross_tenant.reason == "resource_tenant_mismatch"
    assert deleted.allowed is False
    assert deleted.reason == "resource_deleted"


def test_only_tenant_role_managers_can_create_and_revoke_grants(db):
    governor = _actor(
        db,
        user_id="governor",
        role_id="governor-role",
        email="governor@example.com",
        actions={"roles_manage"},
        permission_resource="tenant",
    )
    member = _actor(
        db,
        user_id="member",
        role_id="member-role",
        email="member@example.com",
        actions={"read"},
    )
    db.commit()
    resource = _resource(created_by="owner")
    grants = ResourceGrantService(db)

    grant = grants.create_grant(
        governor,
        "tenant-resource",
        "agent",
        resource,
        subject_role_id="member-role",
        actions=["read"],
    )
    db.commit()

    assert grant.revoked_at is None
    with pytest.raises(Exception):
        grants.create_grant(
            member,
            "tenant-resource",
            "agent",
            resource,
            subject_role_id="member-role",
            actions=["read"],
        )

    grants.revoke_grant(governor, "tenant-resource", grant.id)
    db.commit()
    db.refresh(grant)
    assert grant.revoked_at is not None
