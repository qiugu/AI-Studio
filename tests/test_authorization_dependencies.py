import pytest
import asyncio
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.core.dependencies import require_permission
from app.core.exceptions import ForbiddenException
from app.models import Permission, Role, Tenant, User
from app.models.role_permission import role_permission
from app.models.user_role import user_role
from app.core.dependencies import (
    require_tenant_admin,
    require_tenant_permission,
    require_tenant_user,
    require_platform_permission,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _make_user(
    db: Session,
    *,
    with_permission: bool,
    permission_action: str = "chat",
    is_admin: bool = True,
    is_platform_admin: bool = False,
) -> User:
    tenant = Tenant(id="tenant-dependency", name="Dependency Tenant")
    role = Role(
        tenant_id=tenant.id,
        name="Tenant Admin",
        code="tenant_admin_dependency",
        is_admin=is_admin,
        status=True,
    )
    user = User(
        tenant_id=tenant.id,
        email="dependency@example.com",
        password_hash="hashed",
        status=True,
        email_verified=True,
        is_platform_admin=is_platform_admin,
    )
    db.add_all([tenant, role, user])
    db.flush()
    db.execute(user_role.insert().values(user_id=user.id, role_id=role.id))
    if with_permission:
        permission = Permission(
            resource="agent" if permission_action == "chat" else "tenant",
            action=permission_action,
            description="Permission",
        )
        db.add(permission)
        db.flush()
        db.execute(
            role_permission.insert().values(
                role_id=role.id,
                permission_id=permission.id,
            )
        )
    db.commit()
    db.refresh(user)
    return user


def test_admin_role_without_explicit_permission_is_denied(db):
    user = _make_user(db, with_permission=False)
    checker = require_permission("agent", "chat")

    with pytest.raises(ForbiddenException):
        checker(current_user=user, db=db)


def test_permission_dependency_allows_explicit_role_permission(db):
    user = _make_user(db, with_permission=True)
    checker = require_permission("agent", "chat")

    assert checker(current_user=user, db=db) is user


def test_tenant_admin_guard_accepts_explicit_management_permission(db):
    user = _make_user(
        db,
        with_permission=True,
        permission_action="members_manage",
        is_admin=False,
    )

    result = asyncio.run(require_tenant_admin(current_user=user, db=db))

    assert result is user


def test_tenant_admin_guard_rejects_legacy_admin_without_management_permission(db):
    user = _make_user(db, with_permission=False, is_admin=True)

    with pytest.raises(ForbiddenException):
        asyncio.run(require_tenant_admin(current_user=user, db=db))


def test_tenant_user_guard_rejects_inactive_tenant(db):
    user = _make_user(db, with_permission=True)
    tenant = db.query(Tenant).filter(Tenant.id == user.tenant_id).one()
    tenant.status = False
    db.commit()

    with pytest.raises(ForbiddenException):
        asyncio.run(require_tenant_user(current_user=user, db=db))


def test_tenant_permission_guard_enforces_management_boundary(db):
    user = _make_user(
        db,
        with_permission=True,
        permission_action="members_manage",
        is_admin=False,
    )

    members_checker = require_tenant_permission("members_manage")
    roles_checker = require_tenant_permission("roles_manage")

    assert asyncio.run(members_checker(current_user=user, db=db)) is user
    with pytest.raises(ForbiddenException):
        asyncio.run(roles_checker(current_user=user, db=db))


def test_platform_permission_guard_is_explicit_and_separate(db):
    platform_user = _make_user(db, with_permission=False, is_platform_admin=True)
    checker = require_platform_permission("tenant_provision")

    assert asyncio.run(checker(current_user=platform_user, db=db)) is platform_user
    platform_user.is_platform_admin = False
    db.commit()
    with pytest.raises(ForbiddenException):
        asyncio.run(checker(current_user=platform_user, db=db))
