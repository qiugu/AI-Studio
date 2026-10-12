import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.core.exceptions import ValidationException
from app.models import Tenant, User
from app.schemas.user import UserRoleAssign
from app.services.admin import create_tenant
from app.services.user import assign_roles, create_user


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
