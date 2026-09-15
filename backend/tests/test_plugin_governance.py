"""插件 → Agent 暴露门禁 与 出站安全护栏（P0）单元测试。

覆盖三个层次的断言：

1. **规则层**（``core/plugin_policy.py``）：状态门禁、端点门禁、破坏性动词门禁的
   判据本身。
2. **接线层**（``services/agent.py``）：门禁确实接在工具注册路径上——禁用插件与
   未配端点的绑定会被跳过，且跳过发生在触达数据库之前。
3. **执行层**（``utils/net_guard.py`` / ``utils/plugin_executor.py``）：内网、环回、
   云元数据地址与非 http(s) 协议被拒；路径参数无法改写请求主机。

不依赖 MySQL / Redis / Qdrant，也不发起真实网络请求——SSRF 用例只用 IP 字面量，
因此不触发 DNS 解析。
"""

import os
import sys
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.exceptions import BadRequestException
from app.core.plugin_policy import (
    ALLOW_DESTRUCTIVE_KEY,
    check_plugin_method_gate,
    check_plugin_status_gate,
    has_explicit_endpoint_ref,
)
from app.utils import net_guard
from app.utils.net_guard import assert_outbound_url_allowed, is_ip_blocked
from app.utils.plugin_executor import _substitute_path, execute_plugin_call


# ── 1. 规则层：状态门禁 ─────────────────────────────────────────────────────


@pytest.mark.parametrize("status", ["disabled", "pending_review", "archived", "", None])
def test_status_gate_rejects_non_active(status):
    """仅 active 可暴露：停用 / 待审 / 缺失状态一律拒绝，且给出可读原因。"""
    reason = check_plugin_status_gate(status)
    assert reason is not None
    assert "active" in reason


def test_status_gate_allows_active():
    assert check_plugin_status_gate("active") is None


# ── 2. 规则层：端点门禁 ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "config",
    [
        {"plugin_id": "p1"},
        {"plugin_id": "p1", "endpoint_id": ""},
        {"plugin_id": "p1", "endpoint": ""},
        None,
        "not-a-mapping",
    ],
)
def test_endpoint_ref_requires_explicit_value(config):
    """未显式指定端点即不具备暴露资格——不得回退到"首个端点"。"""
    assert has_explicit_endpoint_ref(config) is False


@pytest.mark.parametrize(
    "config",
    [
        {"endpoint_id": "ep-1"},
        {"endpoint": "/v1/search"},
        {"endpoint_id": "ep-1", "endpoint": "/v1/search"},
    ],
)
def test_endpoint_ref_accepts_explicit_value(config):
    assert has_explicit_endpoint_ref(config) is True


# ── 3. 规则层：破坏性动词门禁 ───────────────────────────────────────────────


@pytest.mark.parametrize("method", ["GET", "POST", "HEAD"])
def test_safe_methods_pass(method):
    assert check_plugin_method_gate(method, {}) is None


@pytest.mark.parametrize("method", ["DELETE", "PUT", "PATCH", "delete"])
def test_destructive_methods_blocked_by_default(method):
    reason = check_plugin_method_gate(method, {})
    assert reason is not None
    assert ALLOW_DESTRUCTIVE_KEY in reason


@pytest.mark.parametrize("method", ["DELETE", "PUT", "PATCH"])
def test_destructive_methods_allowed_with_explicit_flag(method):
    assert check_plugin_method_gate(method, {ALLOW_DESTRUCTIVE_KEY: True}) is None


def test_destructive_flag_must_be_real_boolean():
    """字符串 "true" 不等于显式放行——避免配置误填导致门禁被静默绕过。"""
    assert check_plugin_method_gate("DELETE", {ALLOW_DESTRUCTIVE_KEY: "true"}) is not None


# ── 4. 接线层：门禁接在 Agent 工具注册路径上 ────────────────────────────────


def _make_service():
    """构造不经 __init__ 的 AgentService：本组用例只验证工具构建分支。"""
    from app.services import agent as agent_mod

    svc = agent_mod.AgentService.__new__(agent_mod.AgentService)
    svc.db = None
    svc.tenant_id = "tenant-1"
    return svc


def _make_agent(**tool_config):
    tool = SimpleNamespace(
        tool_type="plugin",
        is_enabled=True,
        name="测试插件工具",
        description=None,
        config=tool_config,
    )
    return SimpleNamespace(tools=[tool])


def test_agent_skips_plugin_without_explicit_endpoint(monkeypatch):
    """未配端点 → 直接跳过，且不查库（证明门禁先于数据库访问）。"""
    from app.services.plugin import PluginService

    def _fail(*_args, **_kwargs):
        raise AssertionError("未配端点的绑定不应触达插件查询")

    monkeypatch.setattr(PluginService, "get", _fail)

    svc = _make_service()
    assert svc._build_langchain_tools(_make_agent(plugin_id="p1")) == []


def test_agent_skips_disabled_plugin(monkeypatch):
    """插件为 disabled → 即使端点已指定也不暴露。"""
    from app.services.plugin import PluginService

    monkeypatch.setattr(
        PluginService,
        "get",
        lambda self, pid: SimpleNamespace(
            status="disabled", name="p", api_spec=None, source_type="http"
        ),
    )

    svc = _make_service()
    agent = _make_agent(plugin_id="p1", endpoint_id="ep-1")
    assert svc._build_langchain_tools(agent) == []


def test_agent_skips_pending_review_plugin(monkeypatch):
    from app.services.plugin import PluginService

    monkeypatch.setattr(
        PluginService,
        "get",
        lambda self, pid: SimpleNamespace(
            status="pending_review", name="p", api_spec=None, source_type="http"
        ),
    )

    svc = _make_service()
    agent = _make_agent(plugin_id="p1", endpoint="/v1/search")
    assert svc._build_langchain_tools(agent) == []


# ── 5. 执行层：IP 范围判定 ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",          # 环回
        "10.0.0.5",           # 私有 A
        "172.16.0.1",         # 私有 B
        "192.168.1.1",        # 私有 C
        "100.64.0.1",         # 运营商级 NAT
        "169.254.169.254",    # 云元数据（链路本地）
        "0.0.0.0",            # 未指定
        "224.0.0.1",          # 组播
        "::1",                # IPv6 环回
        "fe80::1",            # IPv6 链路本地
        "fc00::1",            # IPv6 唯一本地
        "::ffff:127.0.0.1",   # IPv4-mapped IPv6，须还原后再判断
        "not-an-ip",          # 无法解析 → 保守拒绝
    ],
)
def test_blocked_ips(ip):
    assert is_ip_blocked(ip) is True


@pytest.mark.parametrize("ip", ["93.184.216.34", "8.8.8.8", "2606:4700:4700::1111"])
def test_public_ips_allowed(ip):
    assert is_ip_blocked(ip) is False


# ── 6. 执行层：出站 URL 校验 ────────────────────────────────────────────────


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8000/internal",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.5/admin",
        "http://localhost/x",
        "http://api.svc.localhost/x",
        "http://[::1]:9200/_cat/indices",
    ],
)
def test_internal_targets_rejected(url):
    with pytest.raises(BadRequestException):
        assert_outbound_url_allowed(url)


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://93.184.216.34/x",
        "gopher://93.184.216.34/x",
        "",
    ],
)
def test_non_http_schemes_rejected(url):
    with pytest.raises(BadRequestException):
        assert_outbound_url_allowed(url)


def test_public_target_allowed():
    assert_outbound_url_allowed("https://93.184.216.34/v1/search") is None


def test_guard_can_be_disabled_for_internal_deployments(monkeypatch):
    """显式降级开关生效：置 false 后放行内网地址。"""
    monkeypatch.setattr(
        net_guard, "config", SimpleNamespace(plugin_block_private_network=False)
    )
    assert net_guard.assert_outbound_url_allowed("http://10.0.0.5/x") is None


# ── 7. 执行层：路径参数编码与主机不可改写 ───────────────────────────────────


def test_path_param_is_url_encoded():
    params = {"id": "../../admin"}
    path = _substitute_path("/v1/{id}", params)
    assert path == "/v1/..%2F..%2Fadmin"
    # 已消费的路径参数不应重复作为查询参数发送
    assert "id" not in params


def test_path_param_cannot_rewrite_request_host():
    """``//host`` 形态的参数经编码后无法通过 urljoin 改写目标主机。"""
    from urllib.parse import urljoin

    params = {"id": "//127.0.0.1"}
    path = _substitute_path("/v1/{id}", params)
    url = urljoin("http://93.184.216.34" + "/", path.lstrip("/"))
    assert urlsplit(url).hostname == "93.184.216.34"


def test_execute_plugin_call_rejects_internal_base_url():
    """执行入口自身兜底：内网 base_url 在发起请求前即被拒。"""
    with pytest.raises(BadRequestException):
        execute_plugin_call(
            plugin_name="内网插件",
            api_spec=None,
            endpoint_path="/x",
            method="GET",
            config_values={"base_url": "http://127.0.0.1:8080"},
        )


def test_execute_plugin_call_rejects_openapi_internal_server():
    """OpenAPI servers 中的内网地址同样被拒（该地址也由租户提供）。"""
    with pytest.raises(BadRequestException):
        execute_plugin_call(
            plugin_name="内网插件",
            api_spec={"servers": [{"url": "http://169.254.169.254"}]},
            endpoint_path="/latest/meta-data",
            method="GET",
        )


def test_execute_plugin_call_requires_base_url():
    with pytest.raises(BadRequestException):
        execute_plugin_call(
            plugin_name="无地址插件",
            api_spec=None,
            endpoint_path="/x",
            method="GET",
        )
