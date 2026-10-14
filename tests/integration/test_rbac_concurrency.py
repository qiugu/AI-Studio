"""Real-database concurrency checks for RBAC lifecycle invariants.

These tests intentionally run only when an operator supplies a disposable
database through ``RBAC_CONCURRENCY_DATABASE_URL``.  SQLite's emulation of
``SELECT ... FOR UPDATE`` is not sufficient evidence for this contract.
"""

from concurrent.futures import ThreadPoolExecutor
import asyncio
import os
from threading import Barrier
import uuid

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.api import auth as auth_api
from app.core.security import create_access_token, create_refresh_token, decode_token
from app.models import Permission, Role, Tenant, TenantMembership, User
from app.models.membership_role import membership_role
from app.models.role_permission import role_permission
from app.models.user_role import user_role
from app.schemas.role import RoleUpdate
from app.schemas.user import UserUpdate
from app.schemas.auth import RefreshForm
from app.services.role import delete_role, set_role_permissions, update_role
from app.services.user import delete_user, update_user


DATABASE_URL = os.environ.get("RBAC_CONCURRENCY_DATABASE_URL", "").strip()
_MYSQL_DATABASE_URL = DATABASE_URL.startswith(("mysql://", "mysql+"))

pytestmark = pytest.mark.skipif(
    not _MYSQL_DATABASE_URL,
    reason=(
        "set RBAC_CONCURRENCY_DATABASE_URL to a MySQL URL to run real "
        "row-locking checks"
    ),
)


def _seed_single_admin_user(engine):
    suffix = uuid.uuid4().hex
    # Core IDs are varchar(36) UUIDs in the production schema; keep readable
    # labels in names/codes instead of constructing overlong primary keys.
    tenant_id = str(uuid.uuid4())
    owner_id = str(uuid.uuid4())
    target_id = str(uuid.uuid4())
    role_id = str(uuid.uuid4())

    with Session(engine) as db:
        tenant = Tenant(id=tenant_id, name=f"Concurrency {suffix}")
        owner = User(
            id=owner_id,
            tenant_id=tenant_id,
            email=f"owner-{suffix}@example.com",
            password_hash="hashed",
            status=True,
            email_verified=True,
        )
        target = User(
            id=target_id,
            tenant_id=tenant_id,
            email=f"target-{suffix}@example.com",
            password_hash="hashed",
            status=True,
            email_verified=True,
        )
        role = Role(
            id=role_id,
            tenant_id=tenant_id,
            name="Concurrency Admin",
            code=f"concurrency-admin-{suffix}",
            status=True,
            is_admin=True,
        )
        db.add_all([tenant, owner, target, role])
        db.flush()
        tenant.owner_id = owner_id
        db.execute(user_role.insert().values(user_id=target_id, role_id=role_id))
        db.commit()
    return tenant_id, target_id


def _seed_single_admin_role(engine):
    suffix = uuid.uuid4().hex
    tenant_id = str(uuid.uuid4())
    role_id = str(uuid.uuid4())
    with Session(engine) as db:
        tenant = Tenant(id=tenant_id, name=f"Role Concurrency {suffix}")
        role = Role(
            id=role_id,
            tenant_id=tenant_id,
            name="Concurrency Role",
            code=f"concurrency-role-{suffix}",
            status=True,
            is_admin=True,
        )
        db.add(tenant)
        db.flush()
        db.add(role)
        db.flush()
        db.commit()
    return tenant_id, role_id


def _seed_single_admin_role_with_management_permission(engine):
    suffix = uuid.uuid4().hex
    tenant_id = str(uuid.uuid4())
    role_id = str(uuid.uuid4())
    with Session(engine) as db:
        tenant = Tenant(id=tenant_id, name=f"Permission Concurrency {suffix}")
        permission = (
            db.query(Permission)
            .filter(
                Permission.resource == "tenant",
                Permission.action == "members_manage",
            )
            .one()
        )
        role = Role(
            id=role_id,
            tenant_id=tenant_id,
            name="Concurrency Permission Role",
            code=f"concurrency-permission-role-{suffix}",
            status=True,
            is_admin=True,
        )
        db.add(tenant)
        db.flush()
        db.add(role)
        role.permissions.append(permission)
        db.flush()
        db.commit()
    return tenant_id, role_id


def _cleanup_tenant(engine, tenant_id: str) -> None:
    with Session(engine) as db:
        tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
        if tenant is not None:
            tenant.owner_id = None
        user_ids = select(User.id).where(User.tenant_id == tenant_id)
        membership_ids = select(TenantMembership.id).where(
            TenantMembership.tenant_id == tenant_id
        )
        db.execute(
            membership_role.delete().where(
                membership_role.c.membership_id.in_(membership_ids)
            )
        )
        db.execute(user_role.delete().where(user_role.c.user_id.in_(user_ids)))
        db.execute(
            role_permission.delete().where(
                role_permission.c.role_id.in_(
                    select(Role.id).where(Role.tenant_id == tenant_id)
                )
            )
        )
        db.query(TenantMembership).filter(
            TenantMembership.tenant_id == tenant_id
        ).delete(synchronize_session=False)
        db.query(User).filter(User.tenant_id == tenant_id).delete(
            synchronize_session=False
        )
        db.query(Role).filter(Role.tenant_id == tenant_id).delete(
            synchronize_session=False
        )
        db.query(Tenant).filter(Tenant.id == tenant_id).delete(
            synchronize_session=False
        )
        db.commit()


def _run_concurrently(engine, operations):
    barrier = Barrier(len(operations))

    def invoke(operation):
        with Session(engine) as db:
            barrier.wait()
            try:
                operation(db)
                db.commit()
                return "success"
            except Exception as exc:  # noqa: BLE001 - assert exact class below
                db.rollback()
                return type(exc).__name__

    with ThreadPoolExecutor(max_workers=len(operations)) as pool:
        return list(pool.map(invoke, operations))


def test_concurrent_last_admin_user_lifecycle_is_rejected(engine):
    tenant_id, target_id = _seed_single_admin_user(engine)
    try:
        results = _run_concurrently(
            engine,
            [
                lambda db: update_user(
                    target_id,
                    UserUpdate(status=False),
                    tenant_id,
                    db,
                ),
                lambda db: delete_user(target_id, tenant_id, db),
            ],
        )

        assert results == ["ValidationException", "ValidationException"]
        with Session(engine) as db:
            target = db.query(User).filter(User.id == target_id).one()
            assert target.status is True
            assert target.deleted_at is None
    finally:
        _cleanup_tenant(engine, tenant_id)


def test_concurrent_last_admin_role_lifecycle_is_rejected(engine):
    tenant_id, role_id = _seed_single_admin_role(engine)
    try:
        results = _run_concurrently(
            engine,
            [
                lambda db: update_role(
                    role_id,
                    RoleUpdate(status=False),
                    tenant_id,
                    db,
                ),
                lambda db: delete_role(role_id, tenant_id, db),
            ],
        )

        assert results == ["ValidationException", "ValidationException"]
        with Session(engine) as db:
            role = db.query(Role).filter(Role.id == role_id).one()
            assert role.status is True
    finally:
        _cleanup_tenant(engine, tenant_id)


def test_concurrent_last_admin_permission_change_and_deactivation_are_rejected(engine):
    tenant_id, role_id = _seed_single_admin_role_with_management_permission(engine)
    try:
        results = _run_concurrently(
            engine,
            [
                lambda db: set_role_permissions(
                    role_id,
                    [],
                    tenant_id,
                    db,
                ),
                lambda db: update_role(
                    role_id,
                    RoleUpdate(status=False),
                    tenant_id,
                    db,
                ),
            ],
        )

        assert results == ["ValidationException", "ValidationException"]
        with Session(engine) as db:
            role = db.query(Role).filter(Role.id == role_id).one()
            assert role.status is True
            assert len(role.permissions) == 1
    finally:
        _cleanup_tenant(engine, tenant_id)


def test_refresh_token_uses_latest_authorization_version_after_role_change(
    engine, monkeypatch
):
    tenant_id, target_id = _seed_single_admin_user(engine)
    try:
        with Session(engine) as db:
            user = db.query(User).filter(User.id == target_id).one()
            role = (
                db.query(Role)
                .join(user_role, user_role.c.role_id == Role.id)
                .filter(user_role.c.user_id == target_id)
                .one()
            )
            permission = (
                db.query(Permission)
                .filter(
                    Permission.resource == "tenant",
                    Permission.action == "roles_manage",
                )
                .one()
            )
            old_version = user.authz_version
            refresh_token = create_refresh_token(target_id)
            stale_access_token = create_access_token(
                target_id, tenant_id, old_version
            )

            # Role authorization changes are the same invalidation boundary used
            # by the request guard and must be reflected by the next refresh.
            set_role_permissions(role.id, [permission.id], tenant_id, db)
            db.commit()
            db.refresh(user)
            latest_version = user.authz_version

            async def _not_blacklisted(_token):
                return False

            monkeypatch.setattr(auth_api, "_is_token_blacklisted", _not_blacklisted)
            response = asyncio.run(
                auth_api.refresh(
                    RefreshForm(refresh_token=refresh_token),
                    db,
                )
            )
            refreshed_payload = decode_token(response.data["access_token"])

            assert latest_version > old_version
            assert decode_token(stale_access_token)["authz_version"] == old_version
            assert refreshed_payload["authz_version"] == latest_version
    finally:
        _cleanup_tenant(engine, tenant_id)


@pytest.fixture(scope="module")
def engine():
    db_engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        isolation_level="READ COMMITTED",
    )
    try:
        yield db_engine
    finally:
        db_engine.dispose()
