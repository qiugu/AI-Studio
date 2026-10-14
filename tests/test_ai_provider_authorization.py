from sqlalchemy import create_engine
from sqlalchemy.orm import Session
import pytest

from app.core.database import Base
from app.core.exceptions import ForbiddenException
from app.models import Permission, Role, Tenant, User
from app.models.ai_provider import AIProvider
from app.models.user_role import user_role
from app.schemas.ai_provider import AIProviderUpdate
from app.services.ai_provider import AIProviderService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _actor(db: Session, actions: set[str]) -> User:
    tenant = Tenant(id="tenant-provider", name="Provider Tenant")
    role = Role(
        id="provider-role",
        tenant_id=tenant.id,
        name="Provider Role",
        code="provider-role",
        status=True,
    )
    actor = User(
        id="provider-user",
        tenant_id=tenant.id,
        email="provider@example.com",
        password_hash="hashed",
        status=True,
        email_verified=True,
    )
    db.add_all([tenant, role, actor])
    db.flush()
    for action in actions:
        permission = Permission(
            resource="ai_provider", action=action, description=action
        )
        db.add(permission)
        role.permissions.append(permission)
    db.execute(user_role.insert().values(user_id=actor.id, role_id=role.id))
    db.flush()
    return actor


def test_provider_service_rechecks_credential_mutation_permission(db):
    actor = _actor(db, {"read"})
    db.add(
        AIProvider(
            id="provider-1",
            tenant_id=actor.tenant_id,
            name="Provider",
            provider_type="openai",
        )
    )
    db.commit()

    with pytest.raises(ForbiddenException):
        AIProviderService(db, actor.tenant_id, actor=actor).update(
            "provider-1", AIProviderUpdate(api_key="new-secret")
        )
