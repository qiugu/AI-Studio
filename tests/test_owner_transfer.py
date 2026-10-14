from sqlalchemy import create_engine
from sqlalchemy.orm import Session
import pytest

from app.core.database import Base
from app.core.exceptions import ForbiddenException, ValidationException
from app.core.security import hash_password
from app.models import AuditLog, AuthorizationOutbox, Permission, Role, Tenant, User
from app.models.user_role import user_role
from app.services.system import transfer_tenant_owner


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _fixture(db: Session) -> tuple[Tenant, User, User, Role]:
    tenant = Tenant(id="tenant-owner", name="Owner Tenant")
    owner = User(
        id="owner-user",
        tenant_id=tenant.id,
        email="owner@example.com",
        password_hash=hash_password("owner-password"),
        status=True,
        email_verified=True,
        authz_version=3,
    )
    target = User(
        id="target-user",
        tenant_id=tenant.id,
        email="target@example.com",
        password_hash=hash_password("target-password"),
        status=True,
        email_verified=True,
        authz_version=4,
    )
    admin_role = Role(
        id="tenant-admin-role",
        tenant_id=tenant.id,
        name="Tenant Admin",
        code="tenant_admin_owner",
        is_admin=True,
        status=True,
    )
    tenant.owner_id = owner.id
    db.add_all([tenant, owner, target, admin_role])
    db.flush()
    db.execute(user_role.insert().values(user_id=owner.id, role_id=admin_role.id))
    db.commit()
    return tenant, owner, target, admin_role


def test_owner_transfer_is_password_confirmed_idempotent_and_audited(db):
    tenant, owner, target, admin_role = _fixture(db)

    transferred = transfer_tenant_owner(
        tenant.id,
        target.id,
        "owner-password",
        owner,
        db,
    )
    db.commit()

    assert transferred.owner_id == target.id
    assert owner.authz_version == 4
    assert target.authz_version == 5
    assert db.query(user_role).filter(
        user_role.c.user_id == target.id,
        user_role.c.role_id == admin_role.id,
    ).one_or_none() is not None

    audit = db.query(AuditLog).filter(AuditLog.action == "OWNER_TRANSFER").one()
    assert audit.target_id == target.id
    assert audit.metadata_json["previous_owner_id"] == owner.id
    assert "password" not in str(audit.metadata_json).lower()
    outbox = db.query(AuthorizationOutbox).filter(
        AuthorizationOutbox.event_type == "OWNER_TRANSFER"
    ).one()
    assert outbox.status == "pending"
    assert outbox.payload["metadata"]["new_owner_id"] == target.id

    # Repeat with the same target: no ownership change or extra role is created.
    transfer_tenant_owner(
        tenant.id,
        target.id,
        "target-password",
        target,
        db,
    )
    db.commit()
    assert db.query(user_role).filter(
        user_role.c.user_id == target.id,
        user_role.c.role_id == admin_role.id,
    ).count() == 1


def test_owner_transfer_rejects_wrong_actor_password_and_inactive_target(db):
    tenant, owner, target, _admin_role = _fixture(db)
    outsider = User(
        id="outsider-user",
        tenant_id=tenant.id,
        email="outsider@example.com",
        password_hash=hash_password("outsider-password"),
        status=True,
        email_verified=True,
    )
    db.add(outsider)
    db.commit()

    with pytest.raises(ForbiddenException):
        transfer_tenant_owner(
            tenant.id, target.id, "owner-password", outsider, db
        )
    with pytest.raises(ForbiddenException):
        transfer_tenant_owner(
            tenant.id, target.id, "wrong-password", owner, db
        )

    target.status = False
    db.commit()
    with pytest.raises(ValidationException):
        transfer_tenant_owner(
            tenant.id, target.id, "owner-password", owner, db
        )
    assert db.query(Tenant).one().owner_id == owner.id
