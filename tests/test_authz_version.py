from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.core.security import create_access_token, decode_token
from app.models import Permission, Role, Tenant, User
from app.models.user_role import user_role
from app.schemas.user import UserUpdate
from app.services.role import set_role_permissions
from app.services.user import delete_user, update_user


def test_access_token_contains_authorization_version():
    token = create_access_token("user-1", "tenant-1", authz_version=7)

    assert decode_token(token)["authz_version"] == 7


def test_role_permission_change_increments_assigned_user_version():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        tenant = Tenant(id="tenant-version", name="Version Tenant")
        role = Role(
            tenant_id=tenant.id,
            name="Operator",
            code="operator-version",
            status=True,
        )
        user = User(
            tenant_id=tenant.id,
            email="version@example.com",
            password_hash="hashed",
            status=True,
            authz_version=1,
        )
        permission = Permission(resource="agent", action="chat", description="Chat")
        db.add_all([tenant, role, user, permission])
        db.flush()
        db.execute(user_role.insert().values(user_id=user.id, role_id=role.id))
        db.commit()

        set_role_permissions(role.id, [permission.id], tenant.id, db)
        db.refresh(user)

        assert user.authz_version == 2


def test_disabling_user_increments_authorization_version():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        tenant = Tenant(id="tenant-disable", name="Disable Tenant")
        user = User(
            tenant_id=tenant.id,
            email="disable@example.com",
            password_hash="hashed",
            status=True,
            authz_version=3,
        )
        db.add_all([tenant, user])
        db.commit()

        update_user(user.id, UserUpdate(status=False), tenant.id, db)
        db.refresh(user)

        assert user.status is False
        assert user.authz_version == 4


def test_deleting_user_increments_authorization_version():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        tenant = Tenant(id="tenant-delete", name="Delete Tenant")
        user = User(
            tenant_id=tenant.id,
            email="delete@example.com",
            password_hash="hashed",
            status=True,
            authz_version=5,
        )
        db.add_all([tenant, user])
        db.commit()

        delete_user(user.id, tenant.id, db)
        db.refresh(user)

        assert user.deleted_at is not None
        assert user.authz_version == 6
