"""插件对 Agent 的暴露策略（能力暴露门禁）。

**要解决的问题**：此前「插件能被 Agent 调用」与「插件已被绑定到 Agent」是同一件事——
一旦工具条目写入，运行时不再有任何判据（不读 ``plugin.status``、端点可选、动词不限），
于是**禁用插件仍可被调用**、**未指定端点时静默取第一个端点**、**DELETE 端点照常暴露**。

本模块把这些判据集中为**纯函数规则**（不依赖数据库与 FastAPI），既作为运行时的
单一事实源，也让规则可被单测直接覆盖。

三道门禁：

1. **状态门禁** —— 仅 ``active`` 可暴露；``disabled`` / ``pending_review`` 一律拒绝。
   插件停用必须立即全局失能，这是「熔断」的前提。
2. **端点门禁** —— 必须由工具配置**显式**给出 ``endpoint_id`` 或 ``endpoint``。
   不允许「未指定就取第一个端点」的隐式兜底：端点语义不确定，且 OpenAPI 规范中
   破坏性端点（``DELETE``）常排在前面，兜底等于把最危险的端点当成默认值。
3. **破坏性动词门禁** —— ``DELETE`` / ``PUT`` / ``PATCH`` 默认不暴露，
   需在工具配置中显式声明 ``allow_destructive: true`` 才放行。

各 ``check_*`` 函数返回**拒绝原因**（``None`` 表示通过），由调用方负责记录日志并跳过
该工具——即「失败即关闭」（fail-closed），而不是放行。

## 两类判据的分工

| 判据 | 何时生效 | 决定什么 | 函数 |
|------|---------|---------|------|
| **设计期** | 用户创建/编辑 Agent 时 | 「能否出现在选择列表里」「能否写入授权清单」 | ``check_plugin_bindable`` / ``binding_rejection_reason`` |
| **运行时** | Agent 调用工具时 | 「已授权的条目此刻还能否执行」 | ``check_plugin_status_gate`` / ``check_plugin_method_gate`` |

主控点是**设计期**：用户从裁剪过的候选目录中显式挑选，``agent_tools`` 的条目集合
即为该 Agent 的能力边界。运行时判据是**纵深防御**，用于防止授权清单在保存之后
被外部改坏（插件被停用、端点被删除、``base_url`` 被改指内网）。

两类判据共用 ``AGENT_EXPOSABLE_PLUGIN_STATUSES`` / ``DESTRUCTIVE_HTTP_METHODS`` /
``ALLOW_DESTRUCTIVE_KEY`` 等常量，避免口径分裂。
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Optional

from app.core.plugin_source_types import PluginSourceType

# 可被 Agent 调用的插件状态。仅 active；待审与停用均不可暴露。
AGENT_EXPOSABLE_PLUGIN_STATUSES = frozenset({"active"})

# 视为破坏性操作的 HTTP 动词：可能删除或覆盖远端数据，默认不暴露给模型。
# 注：POST 也可能具备破坏性，但语义上过于宽泛，无法一刀切拦截，
# 故本门禁不覆盖 POST——此类端点应由「端点选择」与人工确认（HITL）约束。
DESTRUCTIVE_HTTP_METHODS = frozenset({"DELETE", "PUT", "PATCH"})

# 工具配置中用于显式放行破坏性动词的键名。
ALLOW_DESTRUCTIVE_KEY = "allow_destructive"


def _config_get(config: Optional[Mapping[str, Any]], key: str) -> Any:
    """安全读取工具配置项（配置可能为 None 或非 Mapping）。"""
    if not isinstance(config, Mapping):
        return None
    return config.get(key)


def check_plugin_status_gate(status: Optional[str]) -> Optional[str]:
    """门禁 1：插件状态是否允许暴露给 Agent。"""
    if status in AGENT_EXPOSABLE_PLUGIN_STATUSES:
        return None
    return f"插件状态为 {status or '(未设置)'}，仅 active 插件可被 Agent 调用"


def check_plugin_source_gate(source_type: Optional[str]) -> Optional[str]:
    """运行时门禁 0：接入方式必须已实现（执行器已落地）。

    与设计期 ``check_plugin_bindable`` 共用 ``BINDABLE_SOURCE_TYPES``，避免口径分裂。
    插件被改为 ``mcp`` / ``skill`` 后，原有 http 绑定的运行时调用必须立即失能——
    否则「停用该接入方式」的意图不生效（fail-open）。
    """
    if source_type in BINDABLE_SOURCE_TYPES:
        return None
    return (
        f"接入方式 {source_type or '(未设置)'} 的执行器尚未实现，"
        f"当前仅支持 {'/'.join(sorted(BINDABLE_SOURCE_TYPES))}"
    )


def has_explicit_endpoint_ref(config: Optional[Mapping[str, Any]]) -> bool:
    """门禁 2 的前置判断：工具配置是否显式指定了端点。

    任一项为真即视为显式指定：``endpoint_id``（端点主键）或 ``endpoint``（路径）。
    """
    return bool(
        _config_get(config, "endpoint_id") or _config_get(config, "endpoint")
    )


def check_plugin_method_gate(
    method: Optional[str], config: Optional[Mapping[str, Any]]
) -> Optional[str]:
    """门禁 3：破坏性动词是否已获显式放行。"""
    normalized = (method or "").upper()
    if normalized not in DESTRUCTIVE_HTTP_METHODS:
        return None
    if _config_get(config, ALLOW_DESTRUCTIVE_KEY) is True:
        return None
    return (
        f"端点动词 {normalized} 属破坏性操作，默认不暴露给 Agent；"
        f"确需暴露请在工具配置中显式设置 {ALLOW_DESTRUCTIVE_KEY}=true"
    )


# ── 设计期判据：候选目录与写入校验 ─────────────────────────────────────────
#
# 上文的三个 check_* 是**运行时**判据（决定「已授权的条目此刻还能否执行」）。
# 下面的函数是**设计期**判据（决定「能否出现在用户的选择列表里」与「能否写入授权清单」）。
#
# 二者必须共用同一组常量：若各写一套，就会出现「可选却不可执行」或
# 「可执行却选不到」的口径分裂——而这正是把控制点前移到设计期后最容易踩的坑。

# 可作为 Agent 工具的接入方式。当前仅 http：mcp / skill 的执行器尚未落地，
# 放进候选等于让用户选到「跑不通」的项，属于以错误的方式扩大可选面。
BINDABLE_SOURCE_TYPES = frozenset({PluginSourceType.HTTP.value})


def check_plugin_bindable(
    status: Optional[str],
    source_type: Optional[str],
    endpoint_count: int,
) -> Optional[str]:
    """插件整体能否作为候选绑定给 Agent。返回拒绝原因，``None`` 表示可绑定。

    三重条件：状态为 ``active``、接入方式已实现、至少有一个端点。
    第三个条件是必须的——没有端点的插件即便状态正常，也没有任何东西可以授权。
    """
    reason = check_plugin_status_gate(status)
    if reason:
        return reason
    if source_type not in BINDABLE_SOURCE_TYPES:
        return (
            f"接入方式 {source_type or '(未设置)'} 的执行器尚未实现，"
            f"当前仅支持 {'/'.join(sorted(BINDABLE_SOURCE_TYPES))}"
        )
    if endpoint_count <= 0:
        return "插件未定义任何端点，无可授权的内容"
    return None


def resolve_bound_endpoint(config: Optional[Mapping[str, Any]], endpoints: Any):
    """按工具配置解析目标端点：``endpoint_id`` 优先，其次 ``endpoint`` 路径。

    刻意**不提供**「未指定则取第一个」的兜底：端点语义不确定，且 OpenAPI 规范中
    破坏性端点（``DELETE``）常排在前面，兜底等于把最危险的端点当成默认值。
    无匹配时返回 ``None``，由调用方按 fail-closed 处理。

    参数 ``endpoints`` 只要求元素具备 ``id`` / ``endpoint`` / ``method`` 属性，
    因此设计期（ORM 实体）与单测（轻量替身）可共用同一实现。
    """
    items = list(endpoints or [])
    endpoint_id = _config_get(config, "endpoint_id")
    if endpoint_id:
        for endpoint in items:
            if getattr(endpoint, "id", None) == endpoint_id:
                return endpoint
    endpoint_path = _config_get(config, "endpoint")
    if endpoint_path:
        for endpoint in items:
            if getattr(endpoint, "endpoint", None) == endpoint_path:
                return endpoint
    return None


def _describe_endpoints(endpoints: Any) -> str:
    """把候选端点渲染为 ``METHOD /path`` 列表，供拒绝信息提示用户可选范围。"""
    items = list(endpoints or [])
    if not items:
        return "无"
    return "、".join(
        f"{getattr(e, 'method', '')} {getattr(e, 'endpoint', '')}".strip()
        for e in items
    )


def binding_rejection_reason(
    config: Optional[Mapping[str, Any]],
    plugin: Any,
    endpoints: Any,
) -> Optional[str]:
    """设计期绑定判据：能否把「该插件的某个端点」授权给 Agent。

    返回拒绝原因，``None`` 表示通过。调用方（服务层）负责抛异常或跳过，
    本模块不依赖异常体系，以便规则可被单测直接覆盖。
    """
    reason = check_plugin_bindable(
        getattr(plugin, "status", None),
        getattr(plugin, "source_type", None),
        len(list(endpoints or [])),
    )
    if reason:
        return reason

    endpoint = resolve_bound_endpoint(config, endpoints)
    if endpoint is None:
        return f"未指定有效端点；该插件的候选端点为：{_describe_endpoints(endpoints)}"

    return check_plugin_method_gate(getattr(endpoint, "method", None), config)
