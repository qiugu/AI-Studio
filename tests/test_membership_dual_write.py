from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core import config as config_module
from app.core.database import Base
from app.models import Role, Tenant, TenantMembership, User
from app.models.membership_role import membership_role
from app.models.user_role import user_role
from app.services.admin import create_tenant
from app.services.user import create_user, delete_user, assign_roles, update_user
from app.schemas.user import UserRoleAssign, UserUpdate


def test_membership_dual_write_is_disabled_by_default(monkeypatch):
    monkeypatch.setattr(config_module.config, "membership_dual_write_enabled", False)
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        tenant = Tenant(name="Disabled", max_users=10, max_models=5)
        db.add(tenant)
        db.flush()
        user = create_user(
            "disabled@example.com", "password123", tenant.id, db, check_quota=False
        )
        assert db.query(TenantMembership).filter(
            TenantMembership.user_id == user.id
        ).count() == 0


def test_membership_dual_write_mirrors_create_role_change_and_delete(monkeypatch):
    monkeypatch.setattr(config_module.config, "membership_dual_write_enabled", True)
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        tenant = Tenant(name="Enabled", max_users=10, max_models=5)
        db.add(tenant)
        db.flush()
        user = create_user(
            "enabled@example.com", "password123", tenant.id, db, check_quota=False
        )
        membership = db.query(TenantMembership).filter(
            TenantMembership.user_id == user.id
        ).one()
        legacy_role_ids = {
            role_id for (role_id,) in db.query(user_role.c.role_id)
            .filter(user_role.c.user_id == user.id)
            .all()
        }
        staged_role_ids = {
            role_id for (role_id,) in db.query(membership_role.c.role_id)
            .filter(membership_role.c.membership_id == membership.id)
            .all()
        }
        assert staged_role_ids == legacy_role_ids

        extra_role = Role(
            tenant_id=tenant.id,
            name="Extra",
            code="extra-role",
            status=True,
        )
        db.add(extra_role)
        db.flush()
        assign_roles(
            user.id,
            UserRoleAssign(role_ids=[extra_role.id]),
            tenant.id,
            db,
        )
        staged_role_ids = {
            role_id for (role_id,) in db.query(membership_role.c.role_id)
            .filter(membership_role.c.membership_id == membership.id)
            .all()
        }
        assert staged_role_ids == {extra_role.id}

        delete_user(user.id, tenant.id, db)
        db.refresh(membership)
        assert membership.status is False
        assert db.query(membership_role).filter(
            membership_role.c.membership_id == membership.id
        ).count() == 0


def test_membership_dual_write_mirrors_user_status_changes(monkeypatch):
    monkeypatch.setattr(config_module.config, "membership_dual_write_enabled", True)
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        tenant = Tenant(name="Status Sync", max_users=10, max_models=5)
        db.add(tenant)
        db.flush()
        user = create_user(
            "status-sync@example.com", "password123", tenant.id, db, check_quota=False
        )
        membership = db.query(TenantMembership).filter(
            TenantMembership.user_id == user.id
        ).one()

        update_user(user.id, UserUpdate(status=False), tenant.id, db)
        db.refresh(membership)
        assert membership.status is False
        assert db.query(membership_role).filter(
            membership_role.c.membership_id == membership.id
        ).count() == 0

        update_user(user.id, UserUpdate(status=True), tenant.id, db)
        db.refresh(membership)
        assert membership.status is True
        assert db.query(membership_role).filter(
            membership_role.c.membership_id == membership.id
        ).count() == 1
