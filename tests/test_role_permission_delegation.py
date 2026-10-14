import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.core.exceptions import ForbiddenException, ValidationException
from app.models import Permission, Role, Tenant, User
from app.models.user_role import user_role
from app.services.role import delete_role, list_permissions, set_role_permissions, update_role
from app.schemas.role import RoleUpdate


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _create_role(db: Session) -> Role:
    tenant = Tenant(id="tenant-role-delegation", name="Role Delegation Tenant")
    role = Role(
        tenant_id=tenant.id,
        name="Custom Role",
        code="custom-role-delegation",
        status=True,
    )
    db.add_all([tenant, role])
    db.flush()
    return role


def test_tenant_role_cannot_bind_platform_permission(db):
    role = _create_role(db)
    permission = Permission(
        resource="platform",
        action="tenant_provision",
        description="Provision tenant",
    )
    db.add(permission)
    db.commit()

    with pytest.raises(ValidationException, match="不可委派"):
        set_role_permissions(role.id, [permission.id], role.tenant_id, db)


def test_tenant_role_can_bind_delegable_tenant_permission(db):
    role = _create_role(db)
    permission = Permission(resource="agent", action="chat", description="Chat")
    db.add(permission)
    db.commit()

    updated = set_role_permissions(role.id, [permission.id], role.tenant_id, db)

    assert [item.id for item in updated.permissions] == [permission.id]


def test_tenant_permission_catalog_hides_platform_permissions(db):
    _create_role(db)

    permissions = list_permissions(db)

    assert permissions
    assert all(permission.resource != "platform" for permission in permissions)


def test_role_permission_mutation_locks_tenant_row(db, monkeypatch):
    role = _create_role(db)
    permission = Permission(resource="agent", action="chat", description="Chat")
    db.add(permission)
    db.commit()

    from app.services import role as role_service

    calls: list[str] = []
    original_lock = role_service._lock_tenant_for_mutation

    def record_lock(tenant_id, session):
        calls.append(tenant_id)
        return original_lock(tenant_id, session)

    monkeypatch.setattr(role_service, "_lock_tenant_for_mutation", record_lock)

    set_role_permissions(role.id, [permission.id], role.tenant_id, db)

    assert calls == [role.tenant_id]


def test_role_manager_cannot_delegate_permission_they_do_not_have(db):
    tenant = Tenant(id="tenant-actor", name="Actor Tenant")
    actor_role = Role(
        id="actor-role",
        tenant_id=tenant.id,
        name="Role Manager",
        code="role-manager",
        status=True,
    )
    target_role = Role(
        id="target-role",
        tenant_id=tenant.id,
        name="Target",
        code="target-role",
        status=True,
    )
    actor = User(
        id="actor-user",
        tenant_id=tenant.id,
        email="actor@example.com",
        password_hash="hashed",
        status=True,
        email_verified=True,
    )
    can_manage_roles = Permission(
        resource="tenant", action="roles_manage", description="Manage roles"
    )
    high_risk = Permission(
        resource="agent", action="delete", description="Delete agents"
    )
    actor_role.permissions.append(can_manage_roles)
    target_role.permissions.append(high_risk)
    actor.roles.append(actor_role)
    db.add_all([tenant, actor, target_role])
    db.flush()
    db.commit()

    with pytest.raises(ForbiddenException):
        set_role_permissions(
            target_role.id,
            [high_risk.id],
            tenant.id,
            db,
            actor=actor,
        )


def test_last_custom_admin_role_cannot_be_deleted(db):
    tenant = Tenant(id="tenant-last-admin", name="Last Admin Tenant")
    role = Role(
        id="custom-admin-role",
        tenant_id=tenant.id,
        name="Custom Admin",
        code="custom-admin",
        status=True,
        is_admin=True,
    )
    user = User(
        id="last-admin-user",
        tenant_id=tenant.id,
        email="last-admin@example.com",
        password_hash="hashed",
        status=True,
        email_verified=True,
    )
    user.roles.append(role)
    db.add_all([tenant, user])
    db.commit()

    with pytest.raises(ValidationException, match="管理员"):
        delete_role(role.id, tenant.id, db)


def test_last_admin_role_cannot_lose_all_management_permissions(db):
    tenant = Tenant(id="tenant-last-admin-permissions", name="Permission Guard Tenant")
    role = Role(
        id="last-admin-permission-role",
        tenant_id=tenant.id,
        name="Admin",
        code="last-admin-permission-role",
        status=True,
        is_admin=True,
    )
    manage_members = Permission(
        id="last-admin-members-manage",
        resource="tenant",
        action="members_manage",
        description="Manage tenant members",
    )
    role.permissions.append(manage_members)
    db.add_all([tenant, role])
    db.commit()

    with pytest.raises(ValidationException, match="管理员"):
        set_role_permissions(role.id, [], tenant.id, db)

    db.refresh(role)
    assert [permission.id for permission in role.permissions] == [manage_members.id]


def test_admin_permission_path_can_be_replaced_when_another_path_remains(db):
    tenant = Tenant(id="tenant-two-admin-paths", name="Two Admin Paths Tenant")
    target_role = Role(
        id="admin-path-target-role",
        tenant_id=tenant.id,
        name="Target Admin",
        code="admin-path-target-role",
        status=True,
        is_admin=True,
    )
    remaining_role = Role(
        id="admin-path-remaining-role",
        tenant_id=tenant.id,
        name="Remaining Manager",
        code="admin-path-remaining-role",
        status=True,
    )
    target_permission = Permission(
        id="admin-path-target-permission",
        resource="tenant",
        action="members_manage",
        description="Manage members",
    )
    remaining_permission = Permission(
        id="admin-path-remaining-permission",
        resource="tenant",
        action="roles_manage",
        description="Manage roles",
    )
    target_role.permissions.append(target_permission)
    remaining_role.permissions.append(remaining_permission)
    db.add_all([tenant, target_role, remaining_role])
    db.commit()

    set_role_permissions(target_role.id, [], tenant.id, db)

    assert db.query(Role).filter(Role.id == target_role.id).one().status is True


def test_role_mutations_recheck_service_actor_permission(db):
    tenant = Tenant(id="tenant-role-service", name="Role Service Tenant")
    role = Role(
        id="role-service-target",
        tenant_id=tenant.id,
        name="Target",
        code="target-service",
        status=True,
    )
    actor = User(
        id="role-service-actor",
        tenant_id=tenant.id,
        email="role-service@example.com",
        password_hash="hashed",
        status=True,
        email_verified=True,
    )
    db.add_all([tenant, role, actor])
    db.commit()

    with pytest.raises(ForbiddenException):
        update_role(
            role.id,
            RoleUpdate(name="changed"),
            tenant.id,
            db,
            actor=actor,
        )
    with pytest.raises(ForbiddenException):
        delete_role(role.id, tenant.id, db, actor=actor)
