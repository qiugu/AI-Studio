"""Agent 工具授权（设计期）单元测试。

覆盖三层：

1. **策略层**（``plugin_policy``）——候选裁剪判据与端点解析，纯函数、无依赖；
2. **接线层**（``agent._assert_plugin_tool_bindable``）——非法绑定必须抛异常而非静默跳过；
3. **目录装配层**（``plugin_service.list_bindable_for_agent``）——端点分组与「无端点即排除」。

第三层用轻量假 Session 驱动，不连数据库：被测逻辑是分组与过滤，而非 SQL 本身。

核心回归保护：**不允许「未指定端点则取第一个」**——该兜底会把最危险的端点当成默认值。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.exceptions import NotFoundException, ValidationException
from app.core.plugin_policy import (
    AGENT_EXPOSABLE_PLUGIN_STATUSES,
    BINDABLE_SOURCE_TYPES,
    binding_rejection_reason,
    check_plugin_bindable,
    resolve_bound_endpoint,
)
from app.models.plugin import Plugin, PluginEndpoint
from app.services.agent import AgentService, _assert_plugin_tool_bindable
from app.services.plugin import MAX_BINDABLE_PLUGINS, PluginService


# ── 测试替身 ────────────────────────────────────────────────────────────────


def make_endpoint(ep_id: str, method: str, path: str) -> SimpleNamespace:
    return SimpleNamespace(id=ep_id, method=method, endpoint=path)


def make_plugin(status: str = "active", source_type: str = "http") -> SimpleNamespace:
    return SimpleNamespace(status=status, source_type=source_type)


def make_plugin_tool(config: dict, name: str = "天气查询", tool_type: str = "plugin"):
    return SimpleNamespace(tool_type=tool_type, config=config, name=name)


class _FakeQuery:
    """只实现被测代码实际调用的链式方法。"""

    def __init__(self, items, session):
        self._items = items
        self._session = session

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def limit(self, value):
        # 记录上限，供用例断言「候选面不会无界返回」
        self._session.last_limit = value
        return self

    def all(self):
        return self._items


class _FakeSession:
    def __init__(self, plugins, endpoints):
        self._plugins = plugins
        self._endpoints = endpoints
        self.last_limit = None

    def query(self, model):
        if model is Plugin:
            return _FakeQuery(self._plugins, self)
        if model is PluginEndpoint:
            return _FakeQuery(self._endpoints, self)
        raise AssertionError(f"未预期的查询模型：{model}")


def make_orm_plugin(plugin_id: str, name: str, status="active", source_type="http"):
    return SimpleNamespace(
        id=plugin_id,
        tenant_id="tenant-1",
        name=name,
        status=status,
        source_type=source_type,
        description="描述",
        icon=None,
    )


def make_orm_endpoint(endpoint_id: str, plugin_id: str, method: str, path: str):
    return SimpleNamespace(
        id=endpoint_id,
        plugin_id=plugin_id,
        method=method,
        endpoint=path,
        description=None,
    )


# ── 1. 策略层：候选裁剪判据 ─────────────────────────────────────────────────


class TestCheckPluginBindable:
    def test_active_http_with_endpoint_is_bindable(self):
        assert check_plugin_bindable("active", "http", 1) is None

    @pytest.mark.parametrize("status", ["disabled", "pending_review", "", None])
    def test_non_active_status_rejected(self, status):
        reason = check_plugin_bindable(status, "http", 1)
        assert reason is not None
        assert "active" in reason

    @pytest.mark.parametrize("source_type", ["mcp", "skill", "", None])
    def test_unimplemented_source_type_rejected(self, source_type):
        """mcp / skill 的执行器尚未落地，进了候选等于让用户选到跑不通的项。"""
        reason = check_plugin_bindable("active", source_type, 1)
        assert reason is not None
        assert "尚未实现" in reason

    def test_plugin_without_endpoint_rejected(self):
        reason = check_plugin_bindable("active", "http", 0)
        assert reason is not None
        assert "端点" in reason

    def test_runtime_and_design_time_share_status_set(self):
        """两类判据共用常量，避免「可选却不可执行」的口径分裂。"""
        assert AGENT_EXPOSABLE_PLUGIN_STATUSES == frozenset({"active"})
        assert "http" in BINDABLE_SOURCE_TYPES


class TestResolveBoundEndpoint:
    def test_resolve_by_endpoint_id(self):
        endpoints = [make_endpoint("e1", "GET", "/a"), make_endpoint("e2", "GET", "/b")]
        assert resolve_bound_endpoint({"endpoint_id": "e2"}, endpoints).id == "e2"

    def test_resolve_by_endpoint_path(self):
        endpoints = [make_endpoint("e1", "GET", "/a"), make_endpoint("e2", "GET", "/b")]
        assert resolve_bound_endpoint({"endpoint": "/b"}, endpoints).id == "e2"

    def test_no_implicit_fallback_to_first_endpoint(self):
        """关键回归：未指定端点时必须返回 None，不得取第一个。"""
        endpoints = [make_endpoint("e-danger", "DELETE", "/items/{id}")]
        assert resolve_bound_endpoint({}, endpoints) is None
        assert resolve_bound_endpoint({"endpoint_id": "ghost"}, endpoints) is None
        assert resolve_bound_endpoint({"endpoint": "/nope"}, endpoints) is None

    def test_empty_endpoint_list_is_safe(self):
        assert resolve_bound_endpoint({"endpoint_id": "e1"}, None) is None
        assert resolve_bound_endpoint({"endpoint_id": "e1"}, []) is None


class TestBindingRejectionReason:
    def test_happy_path_passes(self):
        assert (
            binding_rejection_reason(
                {"endpoint_id": "e1"}, make_plugin(), [make_endpoint("e1", "GET", "/a")]
            )
            is None
        )

    def test_destructive_endpoint_requires_explicit_opt_in(self):
        endpoints = [make_endpoint("e1", "DELETE", "/a")]
        reason = binding_rejection_reason({"endpoint_id": "e1"}, make_plugin(), endpoints)
        assert reason is not None
        assert "allow_destructive" in reason

        assert (
            binding_rejection_reason(
                {"endpoint_id": "e1", "allow_destructive": True},
                make_plugin(),
                endpoints,
            )
            is None
        )

    def test_string_true_does_not_pass_the_gate(self):
        """字符串 "true" 不算显式放行，避免配置层以字符串绕过门禁。"""
        endpoints = [make_endpoint("e1", "DELETE", "/a")]
        reason = binding_rejection_reason(
            {"endpoint_id": "e1", "allow_destructive": "true"}, make_plugin(), endpoints
        )
        assert reason is not None

    def test_unknown_endpoint_message_lists_candidates(self):
        endpoints = [make_endpoint("e1", "GET", "/a")]
        reason = binding_rejection_reason({"endpoint_id": "ghost"}, make_plugin(), endpoints)
        assert reason is not None
        assert "GET /a" in reason


# ── 2. 接线层：非法绑定必须抛异常 ───────────────────────────────────────────


class TestAssertPluginToolBindable:
    def test_missing_plugin_id_rejected(self):
        with pytest.raises(ValidationException) as exc:
            _assert_plugin_tool_bindable(0, make_plugin_tool({}), lambda pid: None)
        assert "plugin_id" in str(exc.value.detail)

    def test_unknown_or_cross_tenant_plugin_rejected(self):
        def lookup(_plugin_id):
            raise NotFoundException("Plugin", "p-x")

        with pytest.raises(ValidationException) as exc:
            _assert_plugin_tool_bindable(0, make_plugin_tool({"plugin_id": "p-x"}), lookup)
        assert "不属于当前租户" in str(exc.value.detail)

    def test_disabled_plugin_rejected(self):
        lookup = lambda _pid: (make_plugin(status="disabled"), [make_endpoint("e1", "GET", "/a")])
        with pytest.raises(ValidationException) as exc:
            _assert_plugin_tool_bindable(
                0, make_plugin_tool({"plugin_id": "p1", "endpoint_id": "e1"}), lookup
            )
        assert "active" in str(exc.value.detail)

    def test_error_message_identifies_the_offending_tool(self):
        """拒绝信息须能定位到具体一条，否则多工具表单无法给出可操作的提示。"""
        lookup = lambda _pid: (make_plugin(status="disabled"), [])
        with pytest.raises(ValidationException) as exc:
            _assert_plugin_tool_bindable(
                2, make_plugin_tool({"plugin_id": "p1"}, name="订单工具"), lookup
            )
        assert "第 3 个工具" in str(exc.value.detail)
        assert "订单工具" in str(exc.value.detail)

    def test_valid_binding_passes(self):
        lookup = lambda _pid: (make_plugin(), [make_endpoint("e1", "GET", "/a")])
        _assert_plugin_tool_bindable(
            0, make_plugin_tool({"plugin_id": "p1", "endpoint_id": "e1"}), lookup
        )


class TestValidateToolBindings:
    """``AgentService._validate_tool_bindings`` 的整体行为（fail-closed）。"""

    def _service(self, lookup):
        service = AgentService.__new__(AgentService)
        service.db = None
        service.tenant_id = "tenant-1"
        service._lookup_plugin_for_binding = lookup
        return service

    def test_non_plugin_tools_are_out_of_scope(self):
        """knowledge / api / function / workflow 各有自己的约束，不属本策略范围。"""
        service = self._service(
            lambda _pid: pytest.fail("非 plugin 工具不应触发插件查询")
        )
        service._validate_tool_bindings(
            [
                make_plugin_tool({"knowledge_base_id": "kb1"}, tool_type="knowledge"),
                make_plugin_tool({"url": "https://example.com"}, tool_type="api"),
            ]
        )

    def test_empty_tools_accepted(self):
        service = self._service(lambda _pid: pytest.fail("空列表不应触发查询"))
        service._validate_tool_bindings(None)
        service._validate_tool_bindings([])

    def test_one_bad_binding_fails_the_whole_batch(self):
        """fail-closed：任一条非法即整体失败，不保留部分成功。"""
        good = make_orm_plugin("p-ok", "正常插件")
        bad = make_orm_plugin("p-bad", "停用插件", status="disabled")

        def lookup(plugin_id):
            plugin = {"p-ok": good, "p-bad": bad}[plugin_id]
            return plugin, [make_orm_endpoint("e1", plugin_id, "GET", "/a")]

        service = self._service(lookup)
        with pytest.raises(ValidationException):
            service._validate_tool_bindings(
                [
                    make_plugin_tool({"plugin_id": "p-ok", "endpoint_id": "e1"}),
                    make_plugin_tool({"plugin_id": "p-bad", "endpoint_id": "e1"}),
                ]
            )


# ── 3. 目录装配层：分组与过滤 ───────────────────────────────────────────────


class TestListBindableForAgent:
    def _service(self, plugins, endpoints):
        return PluginService(db=_FakeSession(plugins, endpoints), tenant_id="tenant-1")

    def test_groups_endpoints_by_plugin(self):
        plugins = [make_orm_plugin("p1", "天气"), make_orm_plugin("p2", "订单")]
        endpoints = [
            make_orm_endpoint("e1", "p1", "GET", "/a"),
            make_orm_endpoint("e2", "p1", "POST", "/b"),
            make_orm_endpoint("e3", "p2", "GET", "/c"),
        ]
        result = self._service(plugins, endpoints).list_bindable_for_agent()

        assert [plugin.id for plugin, _ in result] == ["p1", "p2"]
        assert [ep.id for ep in result[0][1]] == ["e1", "e2"]
        assert [ep.id for ep in result[1][1]] == ["e3"]

    def test_plugin_without_endpoint_is_excluded(self):
        """没有端点的插件即便状态正常也无内容可授权，不能出现在候选里。"""
        plugins = [make_orm_plugin("p1", "有端点"), make_orm_plugin("p2", "无端点")]
        endpoints = [make_orm_endpoint("e1", "p1", "GET", "/a")]
        result = self._service(plugins, endpoints).list_bindable_for_agent()

        assert [plugin.id for plugin, _ in result] == ["p1"]

    def test_empty_catalog_is_safe(self):
        assert self._service([], []).list_bindable_for_agent() == []

    def test_catalog_is_a_filtered_tuples_list(self):
        """返回值是 (plugin, endpoints) 元组列表，端点不挂在 ORM 实体上。"""
        plugins = [make_orm_plugin("p1", "天气")]
        endpoints = [make_orm_endpoint("e1", "p1", "GET", "/a")]
        result = self._service(plugins, endpoints).list_bindable_for_agent()

        plugin, eps = result[0]
        assert plugin is plugins[0]
        assert eps == endpoints

    def test_result_size_is_bounded(self):
        """候选面是给用户挑选的，不应无界返回。"""
        service = self._service([], [])

        service.list_bindable_for_agent()
        assert service.db.last_limit == MAX_BINDABLE_PLUGINS

        # 非法取值被收敛到至少 1，避免 limit=0 静默返回空候选
        service.list_bindable_for_agent(limit=0)
        assert service.db.last_limit == 1
