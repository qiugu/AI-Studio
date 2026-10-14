"""Parent-resource inheritance checks for conversations and messages."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.core.exceptions import ForbiddenException, NotFoundException
from app.models import Agent, Conversation, Permission, Role, Tenant, User
from app.services.conversation import ConversationService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _actor(db: Session, tenant_id: str, user_id: str) -> User:
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        tenant = Tenant(id=tenant_id, name=tenant_id)
        db.add(tenant)
        db.flush()
    role = Role(
        id=f"role-{user_id}",
        tenant_id=tenant_id,
        name=user_id,
        code=f"role-{user_id}",
        status=True,
    )
    permission = (
        db.query(Permission)
        .filter(Permission.resource == "agent", Permission.action == "chat")
        .one_or_none()
    )
    if permission is None:
        permission = Permission(
            resource="agent",
            action="chat",
            description="Chat with an agent",
        )
        db.add(permission)
        db.flush()
    role.permissions.append(permission)
    actor = User(
        id=user_id,
        tenant_id=tenant_id,
        email=f"{user_id}@example.com",
        password_hash="hashed",
        status=True,
        email_verified=True,
    )
    actor.roles.append(role)
    db.add(actor)
    db.flush()
    return actor


def test_conversation_id_cannot_cross_tenant_boundary(db):
    actor_a = _actor(db, "tenant-a", "user-a")
    actor_b = _actor(db, "tenant-b", "user-b")
    agent = Agent(
        id="agent-b",
        tenant_id="tenant-b",
        name="B agent",
        model_id="model-b",
        status="published",
        created_by=actor_b.id,
    )
    conversation = Conversation(
        id="conversation-b",
        tenant_id="tenant-b",
        agent_id=agent.id,
        title="B conversation",
        created_by=actor_b.id,
    )
    db.add_all([agent, conversation])
    db.commit()

    with pytest.raises(NotFoundException):
        ConversationService(db, "tenant-a", actor=actor_a).get_conversation(
            conversation.id
        )


def test_conversation_and_message_access_inherit_agent_draft_policy(db):
    owner = _actor(db, "tenant-a", "owner")
    member = _actor(db, "tenant-a", "member")
    agent = Agent(
        id="draft-agent",
        tenant_id="tenant-a",
        name="Draft agent",
        model_id="model-a",
        status="draft",
        created_by=owner.id,
    )
    conversation = Conversation(
        id="draft-conversation",
        tenant_id="tenant-a",
        agent_id=agent.id,
        title="Draft conversation",
        created_by=owner.id,
    )
    db.add_all([agent, conversation])
    db.commit()

    member_service = ConversationService(db, "tenant-a", actor=member)
    with pytest.raises(ForbiddenException):
        member_service.get_conversation(conversation.id)

    agent.status = "published"
    db.commit()
    published = member_service.get_conversation(conversation.id)
    assert published.id == conversation.id
    message = member_service.add_message(conversation.id, "user", "hello")
    assert message.conversation_id == conversation.id
