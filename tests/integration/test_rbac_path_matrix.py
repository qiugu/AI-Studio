"""Matrix checks for cross-tenant IDOR and vertical RBAC boundaries."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.authorization import AuthorizationService
from app.core.database import Base
from app.core.exceptions import ForbiddenException, NotFoundException
from app.models import (
    AIModel,
    AIProvider,
    Agent,
    KnowledgeBase,
    Plugin,
    PluginEndpoint,
    Prompt,
    Role,
    Tenant,
    User,
    Workflow,
)
from app.services.ai_model import AIModelService
from app.services.agent import AgentService
from app.services.knowledge import KnowledgeBaseService
from app.services.plugin import PluginService
from app.services.prompt import PromptService
from app.services.role import ensure_permission_catalog, get_role, list_roles
from app.services.resource_authorization import ResourceAuthorizationService
from app.services.user import get_user_by_id, list_users
from app.services.workflow import WorkflowService
from app.schemas.ai_model import AIModelCreate, AIModelUpdate
from app.schemas.agent import AgentUpdate
from app.schemas.plugin import PluginCreate, PluginUpdate
from app.schemas.prompt import PromptUpdate
from app.schemas.workflow import WorkflowUpdate


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
    permissions: set[tuple[str, str]],
    *,
    owner: bool = False,
) -> User:
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        tenant = Tenant(id=tenant_id, name=tenant_id)
        db.add(tenant)
        db.flush()
    catalog = ensure_permission_catalog(db)
    role = Role(
        id=f"matrix-role-{user_id}",
        tenant_id=tenant_id,
        name=f"Role {user_id}",
        code=f"matrix-role-{user_id}",
        status=True,
    )
    role.permissions.extend(catalog[key] for key in permissions)
    user = User(
        id=user_id,
        tenant_id=tenant_id,
        email=f"{user_id}@example.com",
        password_hash="hashed",
        status=True,
        email_verified=True,
    )
    user.roles.append(role)
    db.add_all([role, user])
    db.flush()
    if owner:
        tenant.owner_id = user.id
    return user


def test_cross_tenant_ids_are_rejected_across_resource_and_admin_services(db):
    actor_a = _actor(
        db,
        "matrix-a",
        "matrix-a-user",
        {
            ("agent", "read"),
            ("workflow", "read"),
            ("prompt", "read"),
            ("knowledge", "read"),
            ("ai_model", "read"),
            ("plugin", "read"),
            ("user", "read"),
            ("role", "read"),
        },
    )
    actor_b = _actor(
        db,
        "matrix-b",
        "matrix-b-user",
        {("agent", "read")},
    )
    provider = AIProvider(
        id="matrix-provider-b",
        tenant_id="matrix-b",
        name="Provider B",
        provider_type="ollama",
    )
    db.add_all(
        [
            provider,
            AIModel(
                id="matrix-model-b",
                tenant_id="matrix-b",
                provider_id=provider.id,
                name="model-b",
                display_name="Model B",
                model_type="chat",
            ),
            Agent(
                id="matrix-agent-b",
                tenant_id="matrix-b",
                name="Agent B",
                model_id="matrix-model-b",
                status="published",
                created_by=actor_b.id,
            ),
            Workflow(
                id="matrix-workflow-b",
                tenant_id="matrix-b",
                name="Workflow B",
                status="published",
                created_by=actor_b.id,
            ),
            Prompt(
                id="matrix-prompt-b",
                tenant_id="matrix-b",
                name="Prompt B",
                status="published",
                created_by=actor_b.id,
            ),
            KnowledgeBase(
                id="matrix-kb-b",
                tenant_id="matrix-b",
                name="KB B",
                created_by=actor_b.id,
            ),
            Plugin(
                id="matrix-plugin-b",
                tenant_id="matrix-b",
                name="Plugin B",
                source_type="http",
                status="active",
            ),
        ]
    )
    db.commit()

    # List paths must never expose a foreign tenant even when the caller has
    # the corresponding read permission.  Each service is exercised here so
    # a regression in one repository filter cannot hide behind the others.
    listed = [
        AgentService(db, actor_a.tenant_id, actor=actor_a).list_agents()[0],
        WorkflowService(db, actor_a.tenant_id, actor=actor_a).list_workflows()[0],
        PromptService(db, actor_a.tenant_id, actor=actor_a).list()[0],
        KnowledgeBaseService(db, actor_a.tenant_id, actor=actor_a).list_knowledge_bases()[0],
        AIModelService(db, actor_a.tenant_id, actor=actor_a).list()[0],
        PluginService(db, actor_a.tenant_id, actor=actor_a).list()[0],
    ]
    assert all(
        str(getattr(item, "tenant_id", "")) == actor_a.tenant_id
        for items in listed
        for item in items
    )
    users, _ = list_users(actor_a.tenant_id, db)
    roles, _ = list_roles(actor_a.tenant_id, db)
    assert all(user.tenant_id == actor_a.tenant_id for user in users)
    assert all(role.tenant_id == actor_a.tenant_id for role in roles)

    with pytest.raises(NotFoundException):
        AgentService(db, actor_a.tenant_id, actor=actor_a).get_agent("matrix-agent-b")
    with pytest.raises(NotFoundException):
        WorkflowService(db, actor_a.tenant_id, actor=actor_a).get_workflow("matrix-workflow-b")
    with pytest.raises(NotFoundException):
        PromptService(db, actor_a.tenant_id, actor=actor_a).get("matrix-prompt-b")
    with pytest.raises(NotFoundException):
        KnowledgeBaseService(db, actor_a.tenant_id, actor=actor_a).get_knowledge_base("matrix-kb-b")
    with pytest.raises(NotFoundException):
        AIModelService(db, actor_a.tenant_id, actor=actor_a).get("matrix-model-b")
    with pytest.raises(NotFoundException):
        PluginService(db, actor_a.tenant_id, actor=actor_a).get("matrix-plugin-b")
    with pytest.raises(NotFoundException):
        get_user_by_id(actor_b.id, actor_a.tenant_id, db)
    with pytest.raises(NotFoundException):
        get_role("matrix-role-matrix-b-user", actor_a.tenant_id, db)

    # Update/delete routes must resolve the resource through the same tenant
    # scoped repository before mutation.  A foreign ID is therefore
    # indistinguishable from a missing resource to the caller.
    with pytest.raises(NotFoundException):
        AgentService(db, actor_a.tenant_id, actor=actor_a).update_agent(
            "matrix-agent-b", AgentUpdate(name="should-not-write")
        )
    with pytest.raises(NotFoundException):
        AgentService(db, actor_a.tenant_id, actor=actor_a).delete_agent("matrix-agent-b")
    with pytest.raises(NotFoundException):
        WorkflowService(db, actor_a.tenant_id, actor=actor_a).update_workflow(
            "matrix-workflow-b", WorkflowUpdate(name="should-not-write")
        )
    with pytest.raises(NotFoundException):
        WorkflowService(db, actor_a.tenant_id, actor=actor_a).delete_workflow(
            "matrix-workflow-b"
        )
    with pytest.raises(NotFoundException):
        PromptService(db, actor_a.tenant_id, actor=actor_a).update(
            "matrix-prompt-b", PromptUpdate(name="should-not-write")
        )
    with pytest.raises(NotFoundException):
        PromptService(db, actor_a.tenant_id, actor=actor_a).delete("matrix-prompt-b")
    with pytest.raises(NotFoundException):
        KnowledgeBaseService(db, actor_a.tenant_id, actor=actor_a).update_knowledge_base(
            "matrix-kb-b", name="should-not-write"
        )
    with pytest.raises(NotFoundException):
        KnowledgeBaseService(db, actor_a.tenant_id, actor=actor_a).delete_knowledge_base(
            "matrix-kb-b"
        )
    with pytest.raises(NotFoundException):
        AIModelService(db, actor_a.tenant_id, actor=actor_a).update(
            "matrix-model-b", AIModelUpdate(name="should-not-write")
        )
    with pytest.raises(NotFoundException):
        AIModelService(db, actor_a.tenant_id, actor=actor_a).delete("matrix-model-b")
    with pytest.raises(NotFoundException):
        PluginService(db, actor_a.tenant_id, actor=actor_a).update(
            "matrix-plugin-b", PluginUpdate(name="should-not-write")
        )
    with pytest.raises(NotFoundException):
        PluginService(db, actor_a.tenant_id, actor=actor_a).delete("matrix-plugin-b")

    # Cover object-level action paths, including export/execute/chat, with a
    # single policy matrix.  The resource tenant check must run before the
    # action-specific owner/publication logic.
    foreign_objects = {
        "agent": db.get(Agent, "matrix-agent-b"),
        "workflow": db.get(Workflow, "matrix-workflow-b"),
        "prompt": db.get(Prompt, "matrix-prompt-b"),
        "knowledge": db.get(KnowledgeBase, "matrix-kb-b"),
        "ai_model": db.get(AIModel, "matrix-model-b"),
        "plugin": db.get(Plugin, "matrix-plugin-b"),
        "user": actor_b,
        "role": db.get(Role, "matrix-role-matrix-b-user"),
    }
    action_matrix = {
        "agent": ("read", "update", "delete", "chat"),
        "workflow": ("read", "update", "delete", "export", "execute"),
        "prompt": ("read", "update", "delete", "test"),
        "knowledge": ("read", "update", "delete", "search"),
        "ai_model": ("read", "update", "delete", "test"),
        "plugin": ("read", "update", "delete", "configure"),
        "user": ("read", "update", "delete", "roles_manage"),
        "role": ("read", "update", "delete", "permissions_manage"),
    }
    resource_auth = ResourceAuthorizationService(db)
    for resource, actions in action_matrix.items():
        for action in actions:
            decision = resource_auth.check(
                actor_a,
                actor_a.tenant_id,
                resource,
                action,
                foreign_objects[resource],
            )
            assert decision.allowed is False
            assert decision.reason == "resource_tenant_mismatch"

    # An endpoint ID from another tenant cannot be used through an otherwise
    # valid plugin path.
    endpoint_b = PluginEndpoint(
        id="matrix-plugin-endpoint-b",
        plugin_id="matrix-plugin-b",
        endpoint="/foreign",
        method="GET",
    )
    db.add(endpoint_b)
    db.commit()
    with pytest.raises(NotFoundException):
        PluginService(db, actor_a.tenant_id, actor=actor_a).list_endpoints(
            "matrix-plugin-b"
        )


def test_vertical_roles_distinguish_draft_edit_published_use_and_audit_read(db):
    owner = _actor(
        db,
        "vertical-tenant",
        "vertical-owner",
        {("agent", "read"), ("agent", "update"), ("agent", "chat")},
        owner=True,
    )
    operator = _actor(
        db,
        "vertical-tenant",
        "vertical-operator",
        {("agent", "read"), ("agent", "chat"), ("workflow", "read"), ("workflow", "execute")},
    )
    auditor = _actor(
        db,
        "vertical-tenant",
        "vertical-auditor",
        {("audit", "read"), ("workflow", "read")},
    )
    agent = Agent(
        id="vertical-draft-agent",
        tenant_id="vertical-tenant",
        name="Draft Agent",
        model_id="model-unused",
        status="draft",
        created_by=owner.id,
    )
    workflow = Workflow(
        id="vertical-published-workflow",
        tenant_id="vertical-tenant",
        name="Published Workflow",
        status="published",
        created_by=owner.id,
    )
    db.add_all([agent, workflow])
    db.commit()

    resource_auth = ResourceAuthorizationService(db)
    assert resource_auth.check(owner, owner.tenant_id, "agent", "update", agent).allowed
    assert not resource_auth.check(operator, operator.tenant_id, "agent", "update", agent).allowed
    assert not resource_auth.check(operator, operator.tenant_id, "agent", "chat", agent).allowed
    agent.status = "published"
    db.commit()
    assert resource_auth.check(operator, operator.tenant_id, "agent", "chat", agent).allowed
    assert not resource_auth.check(auditor, auditor.tenant_id, "workflow", "execute", workflow).allowed
    assert not AuthorizationService(db).check_permission(
        operator, operator.tenant_id, "user", "create"
    ).allowed


def test_tenant_roles_cannot_write_platform_public_resources(db):
    actor = _actor(
        db,
        "public-write-tenant",
        "public-write-user",
        {("ai_model", "read"), ("plugin", "install")},
    )
    provider = AIProvider(
        id="public-write-provider",
        tenant_id=actor.tenant_id,
        name="Provider",
        provider_type="ollama",
    )
    db.add(provider)
    db.commit()

    with pytest.raises(ForbiddenException):
        AIModelService(db, actor.tenant_id, actor=actor).create_public(
            AIModelCreate(
                provider_id=provider.id,
                name="public-model",
                display_name="Public Model",
                model_type="chat",
            )
        )
    with pytest.raises(ForbiddenException):
        PluginService(db, actor.tenant_id, actor=actor).create(
            PluginCreate(name="Public Plugin", is_public=True)
        )
