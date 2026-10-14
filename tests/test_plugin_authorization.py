from sqlalchemy import create_engine
from sqlalchemy.orm import Session
import pytest

from app.core.database import Base
from app.core.exceptions import ForbiddenException
from app.models import Permission, Role, Tenant, User
from app.models.plugin import Plugin
from app.models.user_role import user_role
from app.services.plugin import PluginService
from app.schemas.plugin import PluginUpdate


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _actor(db: Session, actions: set[str]) -> User:
    tenant = Tenant(id="tenant-plugin", name="Plugin Tenant")
    role = Role(
        id="plugin-role",
        tenant_id=tenant.id,
        name="Plugin Role",
        code="plugin-role",
        status=True,
    )
    user = User(
        id="plugin-user",
        tenant_id=tenant.id,
        email="plugin@example.com",
        password_hash="hashed",
        status=True,
        email_verified=True,
    )
    db.add_all([tenant, role, user])
    db.flush()
    for action in actions:
        permission = Permission(
            resource="plugin",
            action=action,
            description=action,
        )
        role.permissions.append(permission)
        db.add(permission)
    db.execute(user_role.insert().values(user_id=user.id, role_id=role.id))
    db.flush()
    return user


def test_plugin_service_rechecks_mutation_permission(db):
    actor = _actor(db, {"read"})
    db.add(Plugin(id="private-plugin", tenant_id=actor.tenant_id, name="Private"))
    db.commit()

    with pytest.raises(ForbiddenException):
        PluginService(db, actor.tenant_id, actor=actor).update(
            "private-plugin", PluginUpdate(name="changed")
        )


def test_tenant_actor_cannot_mutate_public_plugin(db):
    actor = _actor(db, {"update"})
    db.add(
        Plugin(
            id="public-plugin",
            tenant_id=None,
            is_public=True,
            name="Public",
        )
    )
    db.commit()

    with pytest.raises(ForbiddenException):
        PluginService(db, actor.tenant_id, actor=actor).update(
            "public-plugin", PluginUpdate(name="changed")
        )
