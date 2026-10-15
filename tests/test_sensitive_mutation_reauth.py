import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.core.exceptions import ForbiddenException
from app.core.security import hash_password
from app.models import Permission, Role, Tenant, User
from app.models.ai_provider import AIProvider
from app.models.plugin import Plugin
from app.schemas.plugin import (
    PluginConfigItem,
    PluginConfigUpdateRequest,
    PluginEndpointCreate,
)
from app.schemas.role import RoleCreate, RoleUpdate
from app.schemas.user import UserUpdate
from app.schemas.ai_provider import AIProviderUpdate
from app.services.ai_provider import AIProviderService
from app.services.role import create_role, update_role
from app.services.user import update_user
from app.services.plugin import PluginService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _actor(db: Session, permissions: list[tuple[str, str]]) -> User:
    tenant = Tenant(id="reauth-tenant", name="Reauth Tenant")
    actor_role = Role(
        id="reauth-actor-role",
        tenant_id=tenant.id,
        name="Administrator",
        code="reauth-actor-role",
        status=True,
    )
    actor = User(
        id="reauth-actor",
        tenant_id=tenant.id,
        email="reauth-actor@example.com",
        password_hash=hash_password("current-password"),
        status=True,
        email_verified=True,
    )
    actor.roles.append(actor_role)
    db.add_all([tenant, actor])
    db.flush()
    for resource, action in permissions:
        permission = Permission(
            resource=resource,
            action=action,
            description=f"{resource}.{action}",
        )
        actor_role.permissions.append(permission)
    db.flush()
    return actor


def test_role_status_update_requires_current_password(db):
    actor = _actor(db, [("role", "update")])
    role = Role(
        id="reauth-target-role",
        tenant_id=actor.tenant_id,
        name="Target",
        code="reauth-target-role",
        status=True,
    )
    db.add(role)
    db.commit()

    with pytest.raises(ForbiddenException):
        update_role(
            role.id,
            RoleUpdate(status=False),
            actor.tenant_id,
            db,
            actor=actor,
        )

    update_role(
        role.id,
        RoleUpdate(status=False),
        actor.tenant_id,
        db,
        actor=actor,
        current_password="current-password",
    )
    assert role.status is False


def test_role_metadata_update_does_not_require_current_password(db):
    actor = _actor(db, [("role", "update")])
    role = Role(
        id="reauth-role-metadata",
        tenant_id=actor.tenant_id,
        name="Target",
        code="reauth-role-metadata",
        status=True,
    )
    db.add(role)
    db.commit()

    update_role(
        role.id,
        RoleUpdate(name="Renamed", description="Updated description"),
        actor.tenant_id,
        db,
        actor=actor,
    )

    assert role.name == "Renamed"
    assert role.description == "Updated description"


def test_role_without_permissions_does_not_require_current_password(db):
    actor = _actor(db, [("role", "create")])

    role = create_role(
        RoleCreate(name="Empty role", description="No permissions yet"),
        actor.tenant_id,
        db,
        actor=actor,
    )

    assert role.name == "Empty role"


def test_member_status_change_requires_current_password(db):
    actor = _actor(db, [("user", "update"), ("user", "delete")])
    target = User(
        id="reauth-target-user",
        tenant_id=actor.tenant_id,
        email="reauth-target@example.com",
        password_hash=hash_password("target-password"),
        status=True,
        email_verified=True,
    )
    db.add(target)
    db.commit()

    with pytest.raises(ForbiddenException):
        update_user(
            target.id,
            UserUpdate(status=False),
            actor.tenant_id,
            db,
            actor=actor,
        )

    update_user(
        target.id,
        UserUpdate(status=False, current_password="current-password"),
        actor.tenant_id,
        db,
        actor=actor,
    )
    assert target.status is False


def test_provider_credential_config_change_requires_current_password(db):
    actor = _actor(db, [("ai_provider", "update")])
    provider = AIProvider(
        id="reauth-provider",
        tenant_id=actor.tenant_id,
        name="Provider",
        provider_type="openai",
    )
    db.add(provider)
    db.commit()
    service = AIProviderService(db, actor.tenant_id, actor=actor)

    with pytest.raises(ForbiddenException):
        service.update(provider.id, AIProviderUpdate(config={"api_key": "secret"}))

    service.update(
        provider.id,
        AIProviderUpdate(
            config={"api_key": "secret"}, current_password="current-password"
        ),
    )
    assert provider.config == {"api_key": "secret"}


def test_provider_non_secret_config_change_does_not_require_current_password(db):
    actor = _actor(db, [("ai_provider", "update")])
    provider = AIProvider(
        id="reauth-provider-non-secret",
        tenant_id=actor.tenant_id,
        name="Provider",
        provider_type="openai",
    )
    db.add(provider)
    db.commit()

    service = AIProviderService(db, actor.tenant_id, actor=actor)
    service.update(provider.id, AIProviderUpdate(config={"region": "cn"}))

    assert provider.config == {"region": "cn"}


def test_plugin_credential_change_requires_current_password(db, monkeypatch):
    from cryptography.fernet import Fernet
    from pydantic import SecretStr
    import app.core.config as config_module

    monkeypatch.setattr(
        config_module.config,
        "fernet_key",
        SecretStr(Fernet.generate_key().decode()),
    )
    actor = _actor(db, [("plugin", "configure")])
    plugin = Plugin(
        id="reauth-plugin",
        tenant_id=actor.tenant_id,
        name="Plugin",
        source_type="http",
        status="active",
    )
    db.add(plugin)
    db.commit()
    service = PluginService(db, actor.tenant_id, actor=actor)
    request = PluginConfigUpdateRequest(
        items=[PluginConfigItem(name="api_key", value="secret")]
    )

    with pytest.raises(ForbiddenException):
        service.update_config(plugin.id, request)

    request.current_password = "current-password"
    result = service.update_config(plugin.id, request)
    assert result.items[0].has_value is True


def test_plugin_non_secret_config_change_does_not_require_current_password(db, monkeypatch):
    from cryptography.fernet import Fernet
    from pydantic import SecretStr
    import app.core.config as config_module

    monkeypatch.setattr(
        config_module.config,
        "fernet_key",
        SecretStr(Fernet.generate_key().decode()),
    )
    actor = _actor(db, [("plugin", "configure")])
    plugin = Plugin(
        id="reauth-plugin-non-secret",
        tenant_id=actor.tenant_id,
        name="Plugin",
        source_type="http",
        status="active",
    )
    db.add(plugin)
    db.commit()
    service = PluginService(db, actor.tenant_id, actor=actor)

    result = service.update_config(
        plugin.id,
        PluginConfigUpdateRequest(
            items=[PluginConfigItem(name="base_url", value="https://api.example.com")]
        ),
    )

    assert result.items[0].name == "base_url"


def test_plugin_ordinary_headers_do_not_require_current_password(db, monkeypatch):
    from cryptography.fernet import Fernet
    from pydantic import SecretStr
    import app.core.config as config_module

    monkeypatch.setattr(
        config_module.config,
        "fernet_key",
        SecretStr(Fernet.generate_key().decode()),
    )
    actor = _actor(db, [("plugin", "configure")])
    plugin = Plugin(
        id="reauth-plugin-headers",
        tenant_id=actor.tenant_id,
        name="Plugin",
        source_type="http",
        status="active",
    )
    db.add(plugin)
    db.commit()

    result = PluginService(db, actor.tenant_id, actor=actor).update_config(
        plugin.id,
        PluginConfigUpdateRequest(
            items=[PluginConfigItem(name="headers", value={"X-Team": "studio"})]
        ),
    )

    assert result.items[0].name == "headers"


def test_plugin_secret_header_requires_current_password(db, monkeypatch):
    from cryptography.fernet import Fernet
    from pydantic import SecretStr
    import app.core.config as config_module

    monkeypatch.setattr(
        config_module.config,
        "fernet_key",
        SecretStr(Fernet.generate_key().decode()),
    )
    actor = _actor(db, [("plugin", "configure")])
    plugin = Plugin(
        id="reauth-plugin-secret-header",
        tenant_id=actor.tenant_id,
        name="Plugin",
        source_type="http",
        status="active",
    )
    db.add(plugin)
    db.commit()

    with pytest.raises(ForbiddenException):
        PluginService(db, actor.tenant_id, actor=actor).update_config(
            plugin.id,
            PluginConfigUpdateRequest(
                items=[PluginConfigItem(name="headers", value={"X-Api-Key": "secret"})]
            ),
        )


def test_plugin_endpoint_mutation_does_not_require_current_password(db):
    actor = _actor(db, [("plugin", "endpoint_bind")])
    plugin = Plugin(
        id="reauth-plugin-endpoint",
        tenant_id=actor.tenant_id,
        name="Plugin",
        source_type="http",
        status="active",
    )
    db.add(plugin)
    db.commit()

    endpoint = PluginService(db, actor.tenant_id, actor=actor).add_endpoint(
        plugin.id,
        PluginEndpointCreate(endpoint="/v1/search", method="GET"),
    )

    assert endpoint.endpoint == "/v1/search"
