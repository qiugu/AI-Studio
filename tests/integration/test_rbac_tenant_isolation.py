"""Cross-tenant and vertical authorization checks across core resources."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.core.exceptions import ForbiddenException, NotFoundException
from app.models import AIModel, AIProvider, Agent, Permission, Plugin, Role, Tenant, User, Workflow
from app.models.user_role import user_role
from app.services.agent import AgentService
from app.services.ai_model import AIModelService
from app.services.plugin import PluginService
from app.services.resource_authorization import ResourceAuthorizationService
from app.services.workflow import WorkflowService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _actor(
    db: Session,
    tenant_id: str,
    user_id: str,
    permissions: list[tuple[str, str]],
) -> User:
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
    for resource, action in permissions:
        permission = (
            db.query(Permission)
            .filter(Permission.resource == resource, Permission.action == action)
            .one_or_none()
        )
        if permission is None:
            permission = Permission(
                resource=resource,
                action=action,
                description=f"{resource}.{action}",
            )
            db.add(permission)
            db.flush()
        role.permissions.append(permission)
    db.flush()
    return actor


def test_resource_ids_cannot_cross_tenant_service_boundaries(db):
    actor_a = _actor(
        db,
        "tenant-a",
        "user-a",
        [
            ("agent", "read"),
            ("workflow", "read"),
            ("ai_model", "read"),
            ("plugin", "read"),
        ],
    )
    actor_b = _actor(
        db,
        "tenant-b",
        "user-b",
        [("agent", "read"), ("workflow", "read")],
    )
    db.add_all(
        [
            Agent(
                id="agent-b",
                tenant_id="tenant-b",
                name="B agent",
                model_id="model-b",
                status="published",
                created_by=actor_b.id,
            ),
            Workflow(
                id="workflow-b",
                tenant_id="tenant-b",
                name="B workflow",
                status="published",
                created_by=actor_b.id,
            ),
        ]
    )
    db.commit()

    with pytest.raises(NotFoundException):
        AgentService(db, "tenant-a", actor=actor_a).get_agent("agent-b")
    with pytest.raises(NotFoundException):
        WorkflowService(db, "tenant-a", actor=actor_a).get_workflow("workflow-b")


def test_public_resources_are_visible_but_unpublished_rows_are_not(db):
    actor = _actor(
        db,
        "tenant-a",
        "user-a",
        [("ai_model", "read"), ("plugin", "read")],
    )
    db.add_all(
        [
            AIProvider(
                id="provider-public",
                tenant_id="tenant-a",
                name="Provider",
                provider_type="ollama",
            ),
            AIModel(
                id="model-public",
                tenant_id=None,
                provider_id="provider-public",
                name="public-model",
                display_name="Public Model",
                model_type="chat",
                status=True,
            ),
            Plugin(
                id="plugin-public",
                tenant_id=None,
                name="Public Plugin",
                source_type="http",
                status="active",
                is_public=True,
            ),
            Plugin(
                id="plugin-hidden",
                tenant_id=None,
                name="Hidden Plugin",
                source_type="http",
                status="active",
                is_public=False,
            ),
        ]
    )
    db.commit()

    models, _ = AIModelService(db, actor.tenant_id, actor=actor).list(
        include_public=True
    )
    plugins, _ = PluginService(db, actor.tenant_id, actor=actor).list(
        include_public=True
    )
    assert {model.id for model in models} == {"model-public"}
    assert {plugin.id for plugin in plugins} == {"plugin-public"}


def test_vertical_policy_distinguishes_draft_edit_and_published_execution(db):
    owner = _actor(
        db,
        "tenant-a",
        "owner",
        [("agent", "read"), ("agent", "chat"), ("agent", "update")],
    )
    member = _actor(
        db,
        "tenant-a",
        "member",
        [("agent", "read"), ("agent", "chat")],
    )
    auditor = _actor(db, "tenant-a", "auditor", [("workflow", "read")])
    resource = Agent(
        id="draft-agent",
        tenant_id="tenant-a",
        name="Draft",
        model_id="model-a",
        status="draft",
        created_by=owner.id,
    )
    db.add(resource)
    db.commit()
    authorization = ResourceAuthorizationService(db)

    assert authorization.check(
        owner, "tenant-a", "agent", "update", resource
    ).allowed
    assert not authorization.check(
        member, "tenant-a", "agent", "update", resource
    ).allowed
    assert not authorization.check(
        member, "tenant-a", "agent", "chat", resource
    ).allowed

    resource.status = "published"
    db.commit()
    assert authorization.check(
        member, "tenant-a", "agent", "chat", resource
    ).allowed
    with pytest.raises(ForbiddenException):
        authorization.require(auditor, "tenant-a", "agent", "chat", resource)
