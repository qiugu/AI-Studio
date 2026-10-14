import pytest

from app.core.exceptions import ValidationException
from app.core.permissions import get_permission_definition


def test_known_permission_has_stable_metadata():
    definition = get_permission_definition("agent", "chat")

    assert definition.key == "agent.chat"
    assert definition.resource == "agent"
    assert definition.action == "chat"
    assert definition.scope == "tenant"
    assert definition.is_delegable is True


def test_unknown_permission_is_rejected_by_catalog():
    with pytest.raises(ValidationException, match="未知权限"):
        get_permission_definition("agent", "teleport")


def test_platform_permission_is_not_delegable_to_tenant_roles():
    definition = get_permission_definition("platform", "tenant_provision")

    assert definition.key == "platform.tenant_provision"
    assert definition.scope == "platform"
    assert definition.is_delegable is False
