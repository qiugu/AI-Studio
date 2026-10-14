from sqlalchemy import create_engine
from sqlalchemy.orm import Session
import pytest

from app.core.database import Base
from app.core.exceptions import ForbiddenException, NotFoundException
from app.models import Permission, Role, Tenant, User
from app.models.agent import Agent
from app.models.conversation import Conversation
from app.models.user_role import user_role
from app.services.conversation import ConversationService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _actor(db: Session) -> User:
    tenant = Tenant(id="tenant-conversation", name="Conversation Tenant")
    role = Role(
        id="conversation-role",
        tenant_id=tenant.id,
        name="Operator",
        code="conversation-operator",
        status=True,
    )
    permission = Permission(
        resource="agent", action="chat", description="Chat"
    )
    role.permissions.append(permission)
    actor = User(
        id="conversation-user",
        tenant_id=tenant.id,
        email="conversation@example.com",
        password_hash="hashed",
        status=True,
        email_verified=True,
    )
    db.add_all([tenant, role, permission, actor])
    db.flush()
    db.execute(user_role.insert().values(user_id=actor.id, role_id=role.id))
    db.flush()
    return actor


def test_conversation_access_requires_authorized_parent_agent(db):
    actor = _actor(db)
    agent = Agent(
        id="draft-agent",
        tenant_id=actor.tenant_id,
        name="Draft",
        model_id="model-1",
        status="draft",
        created_by="other-user",
    )
    conversation = Conversation(
        id="conversation-1",
        tenant_id=actor.tenant_id,
        agent_id=agent.id,
        created_by="other-user",
    )
    db.add_all([agent, conversation])
    db.commit()

    with pytest.raises(ForbiddenException):
        ConversationService(
            db, actor.tenant_id, actor=actor
        ).get_conversation(conversation.id)


def test_cross_tenant_conversation_is_not_found(db):
    actor = _actor(db)
    other_tenant = Tenant(id="tenant-other", name="Other Tenant")
    agent = Agent(
        id="other-agent",
        tenant_id=other_tenant.id,
        name="Other",
        model_id="model-1",
        status="published",
    )
    conversation = Conversation(
        id="other-conversation",
        tenant_id=other_tenant.id,
        agent_id=agent.id,
    )
    db.add_all([other_tenant, agent, conversation])
    db.commit()

    with pytest.raises(NotFoundException):
        ConversationService(
            db, actor.tenant_id, actor=actor
        ).get_conversation(conversation.id)
