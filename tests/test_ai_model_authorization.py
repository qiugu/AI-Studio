from sqlalchemy import create_engine
from sqlalchemy.orm import Session
import pytest

from app.core.database import Base
from app.core.exceptions import ForbiddenException
from app.models import Permission, Role, Tenant, User
from app.models.ai_model import AIModel
from app.models.user_role import user_role
from app.schemas.ai_model import AIModelUpdate
from app.services.ai_model import AIModelService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _actor(db: Session, actions: set[str]) -> User:
    tenant = Tenant(id="tenant-model", name="Model Tenant")
    role = Role(
        id="model-role",
        tenant_id=tenant.id,
        name="Model Role",
        code="model-role",
        status=True,
    )
    user = User(
        id="model-user",
        tenant_id=tenant.id,
        email="model@example.com",
        password_hash="hashed",
        status=True,
        email_verified=True,
    )
    db.add_all([tenant, role, user])
    db.flush()
    for action in actions:
        permission = Permission(resource="ai_model", action=action, description=action)
        db.add(permission)
        role.permissions.append(permission)
    db.execute(user_role.insert().values(user_id=user.id, role_id=role.id))
    db.flush()
    return user


def test_public_model_is_readable_but_not_mutable_by_tenant_actor(db):
    actor = _actor(db, {"read", "update"})
    db.add(
        AIModel(
            id="public-model",
            tenant_id=None,
            provider_id="provider-1",
            name="public",
            display_name="Public",
            model_type="chat",
        )
    )
    db.commit()

    service = AIModelService(db, actor.tenant_id, actor=actor)
    assert service.get("public-model").tenant_id is None
    with pytest.raises(ForbiddenException):
        service.update("public-model", AIModelUpdate(display_name="changed"))


def test_model_service_rechecks_mutation_permission(db):
    actor = _actor(db, {"read"})
    db.add(
        AIModel(
            id="private-model",
            tenant_id=actor.tenant_id,
            provider_id="provider-1",
            name="private",
            display_name="Private",
            model_type="chat",
        )
    )
    db.commit()

    with pytest.raises(ForbiddenException):
        AIModelService(db, actor.tenant_id, actor=actor).update(
            "private-model", AIModelUpdate(display_name="changed")
        )
