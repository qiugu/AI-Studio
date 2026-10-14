import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.core.exceptions import ForbiddenException, ValidationException
from app.models import AuditLog, Permission, Role, Tenant, User
from app.models.user_role import user_role
from app.schemas.user import UserRoleAssign
from app.services.admin import create_tenant
from app.services.user import assign_roles, build_user_payload, create_user, delete_user, update_user
from app.schemas.user import UserUpdate


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_platform_tenant_creation_assigns_initial_admin_role(db):
    tenant = create_tenant(
        {
            "name": "Tenant",
            "admin_email": "owner@example.com",
            "admin_password": "password123",
        },
        db,
    )

    user = db.query(User).filter(User.email == "owner@example.com").one()
    db.refresh(user)
    assert tenant.owner_id == user.id
    assert [role.code for role in user.roles] == [f"tenant_admin_{tenant.id}"]
    assert user.roles[0].is_admin is True


def test_platform_tenant_creation_grants_only_tenant_permissions_to_admin(db):
    tenant = create_tenant(
        {
            "name": "Permission Tenant",
            "admin_email": "permission-owner@example.com",
            "admin_password": "password123",
        },
        db,
    )

    user = db.query(User).filter(User.email == "permission-owner@example.com").one()
    permissions = {(item.resource, item.action) for item in user.roles[0].permissions}

    assert ("agent", "chat") in permissions
    assert ("platform", "tenant_provision") not in permissions


def test_user_payload_exposes_backend_capability_snapshot(db):
    tenant = create_tenant(
        {
            "name": "Capability Tenant",
            "admin_email": "capability-owner@example.com",
            "admin_password": "password123",
        },
        db,
    )
    user = db.query(User).filter(User.email == "capability-owner@example.com").one()

    payload = build_user_payload(user, db)

    assert "agent.chat" in payload["capabilities"]
    assert "tenant.roles_manage" in payload["capabilities"]
    assert "platform.tenant_provision" not in payload["capabilities"]


def test_create_user_defaults_to_tenant_member_role(db):
    tenant = Tenant(name="Tenant", plan="free", max_users=10, max_models=5)
    db.add(tenant)
    db.flush()

    user = create_user(
        email="member@example.com",
        password="password123",
        tenant_id=tenant.id,
        db=db,
        check_quota=False,
    )

    db.refresh(user)
    assert [role.code for role in user.roles] == [f"tenant_member_{tenant.id}"]


def test_create_user_rejects_unknown_roles_instead_of_creating_unassigned_user(db):
    tenant = Tenant(name="Tenant", plan="free", max_users=10, max_models=5)
    db.add(tenant)
    db.flush()

    with pytest.raises(ValidationException):
        create_user(
            email="member@example.com",
            password="password123",
            tenant_id=tenant.id,
            db=db,
            check_quota=False,
            role_ids=["missing-role"],
        )

    assert db.scalar(select(User).where(User.email == "member@example.com")) is None


def test_assigning_empty_roles_keeps_user_in_default_member_role(db):
    tenant = Tenant(name="Tenant", plan="free", max_users=10, max_models=5)
    db.add(tenant)
    db.flush()
    user = create_user(
        email="member@example.com",
        password="password123",
        tenant_id=tenant.id,
        db=db,
        check_quota=False,
    )

    assign_roles(user.id, UserRoleAssign(role_ids=[]), tenant.id, db)

    db.refresh(user)
    assert [role.code for role in user.roles] == [f"tenant_member_{tenant.id}"]


def test_member_manager_cannot_assign_a_role_with_unowned_permissions(db):
    tenant = Tenant(id="tenant-user-delegation", name="User Delegation Tenant")
    actor_role = Role(
        id="member-manager-role",
        tenant_id=tenant.id,
        name="Member Manager",
        code="member-manager",
        status=True,
    )
    target_role = Role(
        id="high-risk-role",
        tenant_id=tenant.id,
        name="High Risk",
        code="high-risk",
        status=True,
    )
    actor = User(
        id="member-manager-user",
        tenant_id=tenant.id,
        email="member-manager@example.com",
        password_hash="hashed",
        status=True,
        email_verified=True,
    )
    target = User(
        id="target-user",
        tenant_id=tenant.id,
        email="target@example.com",
        password_hash="hashed",
        status=True,
        email_verified=True,
    )
    member_permission = Permission(
        resource="tenant", action="members_manage", description="Manage members"
    )
    high_risk_permission = Permission(
        resource="agent", action="delete", description="Delete agents"
    )
    actor_role.permissions.append(member_permission)
    target_role.permissions.append(high_risk_permission)
    actor.roles.append(actor_role)
    db.add_all([tenant, actor, target, target_role])
    db.commit()

    with pytest.raises(ForbiddenException):
        assign_roles(
            target.id,
            UserRoleAssign(role_ids=[target_role.id]),
            tenant.id,
            db,
            actor=actor,
        )


def test_tenant_owner_cannot_be_deleted_or_demoted(db):
    tenant = create_tenant(
        {
            "name": "Owner Protection Tenant",
            "admin_email": "owner-protection@example.com",
            "admin_password": "password123",
        },
        db,
    )
    owner = db.query(User).filter(User.id == tenant.owner_id).one()
    member_role = (
        db.query(Role)
        .filter(Role.tenant_id == tenant.id, Role.code == f"tenant_member_{tenant.id}")
        .one()
    )

    with pytest.raises(ValidationException, match="所有者"):
        update_user(
            owner.id,
            UserUpdate(role_ids=[member_role.id]),
            tenant.id,
            db,
        )
    with pytest.raises(ValidationException, match="所有权"):
        delete_user(owner.id, tenant.id, db)


def test_deactivating_last_active_admin_user_is_rejected(db):
    tenant = create_tenant(
        {
            "name": "Last Admin Status Tenant",
            "admin_email": "last-admin-owner@example.com",
            "admin_password": "password123",
        },
        db,
    )
    admin_role = db.query(Role).filter(
        Role.tenant_id == tenant.id,
        Role.is_admin.is_(True),
    ).one()
    target = create_user(
        email="last-admin-target@example.com",
        password="password123",
        tenant_id=tenant.id,
        db=db,
        check_quota=False,
        role_ids=[admin_role.id],
    )
    owner = db.query(User).filter(User.id == tenant.owner_id).one()
    # Reproduce a legacy/inconsistent row set where the owner has lost the
    # admin role; the service must still preserve the final active admin user.
    db.execute(user_role.delete().where(user_role.c.user_id == owner.id))
    db.flush()

    with pytest.raises(ValidationException, match="管理员"):
        update_user(
            target.id,
            UserUpdate(status=False),
            tenant.id,
            db,
        )

    db.refresh(target)
    assert target.status is True


def test_deleting_last_active_admin_user_is_rejected(db):
    tenant = create_tenant(
        {
            "name": "Last Admin Delete Tenant",
            "admin_email": "last-delete-owner@example.com",
            "admin_password": "password123",
        },
        db,
    )
    admin_role = db.query(Role).filter(
        Role.tenant_id == tenant.id,
        Role.is_admin.is_(True),
    ).one()
    target = create_user(
        email="last-delete-target@example.com",
        password="password123",
        tenant_id=tenant.id,
        db=db,
        check_quota=False,
        role_ids=[admin_role.id],
    )
    owner = db.query(User).filter(User.id == tenant.owner_id).one()

    # Reproduce a legacy/inconsistent row set where the owner has lost the
    # admin role; the service must still refuse deleting the last active admin
    # user instead of relying only on owner_id.
    db.execute(user_role.delete().where(user_role.c.user_id == owner.id))
    db.flush()

    with pytest.raises(ValidationException, match="管理员"):
        delete_user(target.id, tenant.id, db)

    db.refresh(target)
    assert target.deleted_at is None


def test_user_mutations_recheck_service_actor_permission(db):
    tenant = Tenant(id="tenant-user-service", name="User Service Tenant")
    actor_role = Role(
        id="user-service-actor-role",
        tenant_id=tenant.id,
        name="Viewer",
        code="user-service-viewer",
        status=True,
    )
    actor = User(
        id="user-service-actor",
        tenant_id=tenant.id,
        email="viewer@example.com",
        password_hash="hashed",
        status=True,
        email_verified=True,
    )
    target = User(
        id="user-service-target",
        tenant_id=tenant.id,
        email="target-service@example.com",
        password_hash="hashed",
        status=True,
        email_verified=True,
    )
    actor.roles.append(actor_role)
    db.add_all([tenant, actor, target])
    db.commit()

    with pytest.raises(ForbiddenException):
        update_user(
            target.id,
            UserUpdate(status=False),
            tenant.id,
            db,
            actor=actor,
        )
    with pytest.raises(ForbiddenException):
        delete_user(target.id, tenant.id, db, actor=actor)
    with pytest.raises(ForbiddenException):
        create_user(
            email="new-service@example.com",
            password="password123",
            tenant_id=tenant.id,
            db=db,
            check_quota=False,
            actor=actor,
        )


def test_tenant_admin_cannot_set_another_users_password(db):
    tenant = create_tenant(
        {
            "name": "Password Boundary Tenant",
            "admin_email": "password-boundary-owner@example.com",
            "admin_password": "password123",
        },
        db,
    )
    owner = db.query(User).filter(User.id == tenant.owner_id).one()
    target = create_user(
        email="password-boundary-target@example.com",
        password="target-password",
        tenant_id=tenant.id,
        db=db,
        check_quota=False,
    )
    original_hash = target.password_hash

    with pytest.raises(ValidationException, match="密码重置"):
        update_user(
            target.id,
            UserUpdate(password="admin-chosen-password", current_password="password123"),
            tenant.id,
            db,
            actor=owner,
        )

    db.refresh(target)
    assert target.password_hash == original_hash


def test_nickname_change_audit_keeps_stable_identity_snapshot(db):
    tenant = create_tenant(
        {
            "name": "Identity Audit Tenant",
            "admin_email": "identity-audit-owner@example.com",
            "admin_password": "password123",
        },
        db,
    )
    owner = db.query(User).filter(User.id == tenant.owner_id).one()
    target = create_user(
        email="identity-audit-target@example.com",
        password="target-password",
        nickname="旧昵称",
        tenant_id=tenant.id,
        db=db,
        check_quota=False,
    )

    update_user(
        target.id,
        UserUpdate(nickname="新昵称"),
        tenant.id,
        db,
        actor=owner,
    )
    audit = (
        db.query(AuditLog)
        .filter(
            AuditLog.action == "USER_UPDATED",
            AuditLog.target_id == target.id,
        )
        .order_by(AuditLog.created_at.desc())
        .first()
    )

    assert audit is not None
    assert audit.metadata_json["target_user_id"] == target.id
    assert audit.metadata_json["target_email"] == target.email
    assert audit.metadata_json["nickname_before"] == "旧昵称"
    assert audit.metadata_json["nickname_after"] == "新昵称"
