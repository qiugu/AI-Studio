"""Stable permission catalog for tenant and platform authorization."""
from dataclasses import dataclass

from app.core.exceptions import ValidationException


@dataclass(frozen=True)
class PermissionDefinition:
    key: str
    resource: str
    action: str
    description: str
    scope: str = "tenant"
    sensitivity: str = "normal"
    is_delegable: bool = True


def _definition(
    resource: str,
    action: str,
    description: str,
    *,
    scope: str = "tenant",
    sensitivity: str = "normal",
    is_delegable: bool = True,
) -> PermissionDefinition:
    return PermissionDefinition(
        key=f"{resource}.{action}",
        resource=resource,
        action=action,
        description=description,
        scope=scope,
        sensitivity=sensitivity,
        is_delegable=is_delegable,
    )


_DEFINITIONS = [
    _definition("tenant", "read", "查看租户信息"),
    _definition("tenant", "settings", "管理租户设置", sensitivity="high"),
    _definition("tenant", "members_read", "查看租户成员"),
    _definition("tenant", "members_manage", "管理租户成员", sensitivity="high"),
    _definition("tenant", "roles_read", "查看租户角色"),
    _definition("tenant", "roles_manage", "管理租户角色", sensitivity="high"),
    _definition("tenant", "audit_read", "查看审计日志", sensitivity="high"),
    _definition("tenant", "usage_read", "查看租户用量"),
    _definition("user", "read", "查看用户"),
    _definition("user", "create", "创建用户"),
    _definition("user", "update", "更新用户"),
    _definition("user", "delete", "停用用户", sensitivity="high"),
    _definition("user", "roles_manage", "分配用户角色", sensitivity="high"),
    _definition("role", "read", "查看角色"),
    _definition("role", "create", "创建角色"),
    _definition("role", "update", "更新角色"),
    _definition("role", "delete", "删除角色", sensitivity="high"),
    _definition("role", "permissions_manage", "管理角色权限", sensitivity="high"),
    _definition("audit", "read", "查看审计日志", sensitivity="high"),
    _definition("dashboard", "read", "查看租户仪表盘"),
    _definition("quota", "read", "查看租户配额"),
    _definition("ai_provider", "read", "查看 AI 供应商"),
    _definition("ai_provider", "create", "创建 AI 供应商", sensitivity="high"),
    _definition("ai_provider", "update", "更新 AI 供应商", sensitivity="high"),
    _definition("ai_provider", "delete", "删除 AI 供应商", sensitivity="high"),
    _definition("ai_provider", "test", "测试 AI 供应商", sensitivity="high"),
    _definition("ai_model", "read", "查看 AI 模型"),
    _definition("ai_model", "create", "创建 AI 模型", sensitivity="high"),
    _definition("ai_model", "update", "更新 AI 模型", sensitivity="high"),
    _definition("ai_model", "delete", "删除 AI 模型", sensitivity="high"),
    _definition("ai_model", "test", "测试 AI 模型", sensitivity="high"),
    _definition("prompt", "read", "查看 Prompt"),
    _definition("prompt", "create", "创建 Prompt"),
    _definition("prompt", "update", "编辑 Prompt"),
    _definition("prompt", "delete", "删除 Prompt"),
    _definition("prompt", "publish", "发布 Prompt"),
    _definition("prompt", "test", "测试 Prompt"),
    _definition("knowledge", "read", "查看知识库"),
    _definition("knowledge", "create", "创建知识库"),
    _definition("knowledge", "update", "编辑知识库"),
    _definition("knowledge", "delete", "删除知识库"),
    _definition("knowledge", "upload", "上传知识库文档"),
    _definition("knowledge", "search", "检索知识库"),
    _definition("agent", "read", "查看 Agent"),
    _definition("agent", "create", "创建 Agent"),
    _definition("agent", "update", "编辑 Agent"),
    _definition("agent", "delete", "删除 Agent"),
    _definition("agent", "publish", "发布 Agent"),
    _definition("agent", "chat", "使用 Agent 对话"),
    _definition("agent", "tools_manage", "管理 Agent 工具", sensitivity="high"),
    _definition("workflow", "read", "查看工作流"),
    _definition("workflow", "create", "创建工作流"),
    _definition("workflow", "update", "编辑工作流"),
    _definition("workflow", "delete", "删除工作流"),
    _definition("workflow", "publish", "发布工作流"),
    _definition("workflow", "execute", "执行工作流"),
    _definition("workflow", "export", "导出工作流"),
    _definition("plugin", "read", "查看插件"),
    _definition("plugin", "install", "安装插件", sensitivity="high"),
    _definition("plugin", "configure", "配置插件", sensitivity="high"),
    _definition("plugin", "update", "更新插件", sensitivity="high"),
    _definition("plugin", "delete", "删除插件", sensitivity="high"),
    _definition("plugin", "endpoint_bind", "绑定插件端点", sensitivity="high"),
    _definition(
        "platform",
        "tenant_provision",
        "开通租户",
        scope="platform",
        sensitivity="critical",
        is_delegable=False,
    ),
    _definition(
        "platform",
        "permission_catalog_manage",
        "管理平台权限目录",
        scope="platform",
        sensitivity="critical",
        is_delegable=False,
    ),
    _definition(
        "platform",
        "public_model_manage",
        "管理公共模型",
        scope="platform",
        sensitivity="critical",
        is_delegable=False,
    ),
    _definition(
        "platform",
        "public_plugin_manage",
        "管理公共插件",
        scope="platform",
        sensitivity="critical",
        is_delegable=False,
    ),
]

PERMISSION_CATALOG = {item.key: item for item in _DEFINITIONS}


def get_permission_definition(resource: str, action: str) -> PermissionDefinition:
    key = f"{resource}.{action}"
    definition = PERMISSION_CATALOG.get(key)
    if definition is None:
        raise ValidationException(f"未知权限: {key}")
    return definition


def get_permission_definitions(resource: str) -> tuple[PermissionDefinition, ...]:
    """Return the catalog entries for one resource in stable display order."""
    return tuple(item for item in _DEFINITIONS if item.resource == resource)


def is_permission_delegable(resource: str, action: str) -> bool:
    return get_permission_definition(resource, action).is_delegable
