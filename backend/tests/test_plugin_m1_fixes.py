"""M1 修复的回归测试：插件使用流程评审（docs/plugin-usage-flow-review.md）。

覆盖：
- M1-1：更新 Agent 时仅重建 plugin 类工具，保留 knowledge/api/function/workflow（§3.1）
- M1-2：运行时门禁补 source_type 判据（§3.3）
- M1-3：插件凭据加密存储 + 脱敏回显（§3.2）
- M1-4：update_config 写入契约（支持删除 + required 校验，P1-C1 / P1-C4）
- M1-5：端点 request_body_schema 接入 Agent 工具参数（P1-C11）

集成测试使用内存 SQLite（``Base.metadata.create_all``），无需连真实数据库；
加密相关用例用 monkeypatch 注入 FERNET_KEY，与 test_encryption.py 一致。
"""
from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.agent import Agent
from app.models.agent_tool import AgentTool
from app.models.plugin import Plugin, PluginEndpoint, PluginConfig
from app.schemas.agent import AgentUpdate, AgentToolCreate
from app.schemas.plugin import PluginConfigUpdateRequest, PluginConfigItem
from app.services.agent import AgentService, _build_args_schema
from app.services.plugin import PluginService
from app.core.plugin_policy import (
    BINDABLE_SOURCE_TYPES,
    check_plugin_source_gate,
)
from app.core.exceptions import ValidationException


# ── 基础设施 ────────────────────────────────────────────────────────────────


@pytest.fixture
def session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session_ = sessionmaker(bind=engine)
    db = Session_()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


@pytest.fixture
def fernet(monkeypatch):
    """注入测试用 FERNET_KEY（与 test_encryption.py 一致）。"""
    from cryptography.fernet import Fernet
    from pydantic import SecretStr

    import app.core.config as cfg_module

    key = Fernet.generate_key().decode()
    monkeypatch.setattr(cfg_module.config, "fernet_key", SecretStr(key))
    return key


def _oid() -> str:
    return str(uuid.uuid4())


def _make_agent(db: Session, tenant: str, aid: str = "a1") -> Agent:
    agent = Agent(
        id=aid, tenant_id=tenant, name="agent", model_id=_oid(), status="published"
    )
    db.add(agent)
    db.flush()
    return agent


def _make_plugin(db: Session, tenant: str, pid: str = "p1") -> Plugin:
    plugin = Plugin(
        id=pid, tenant_id=tenant, name="P", status="active",
        source_type="http",
    )
    db.add(plugin)
    db.add(PluginEndpoint(id="e1", plugin_id=pid, method="POST", endpoint="/v1/x"))
    db.flush()
    return plugin


# ── M1-2：运行时 source_type 门禁 ────────────────────────────────────────────


class TestRuntimeSourceGate:
    def test_http_passes(self):
        assert check_plugin_source_gate("http") is None

    @pytest.mark.parametrize("source_type", ["mcp", "skill", "", None])
    def test_unimplemented_source_rejected(self, source_type):
        reason = check_plugin_source_gate(source_type)
        assert reason is not None
        assert "尚未实现" in reason

    def test_uses_shared_bindable_set(self):
        # 运行时与设计期共用同一常量，避免口径分裂（修复 fail-open）
        assert check_plugin_source_gate("http") is None
        assert "http" in BINDABLE_SOURCE_TYPES


# ── M1-1：更新 Agent 保留非插件工具 ─────────────────────────────────────────


class TestUpdateAgentPreservesNonPluginTools:
    def test_knowledge_tool_survives_plugin_only_update(self, session):
        tenant = "t1"
        _make_agent(session, tenant)
        _make_plugin(session, tenant)
        # 既有：一个 plugin 工具 + 一个 knowledge 工具
        session.add(AgentTool(
            id="at-plugin", tenant_id=tenant, agent_id="a1",
            tool_type="plugin", config={"plugin_id": "p1", "endpoint": "/v1/x"},
            name="wx", is_enabled=True,
        ))
        session.add(AgentTool(
            id="at-kb", tenant_id=tenant, agent_id="a1",
            tool_type="knowledge", config={"knowledge_base_id": "kb1"},
            name="kb", is_enabled=True,
        ))
        session.commit()

        svc = AgentService(session, tenant)
        svc.update_agent(
            "a1",
            AgentUpdate(tools=[
                AgentToolCreate(
                    tool_type="plugin",
                    config={"plugin_id": "p1", "endpoint": "/v1/x"},
                    name="wx", is_enabled=True,
                )
            ]),
        )

        tools = session.query(AgentTool).filter(
            AgentTool.agent_id == "a1"
        ).all()
        types = {t.tool_type for t in tools}
        assert "knowledge" in types, "knowledge 工具不应被清空"
        plugin_tools = [t for t in tools if t.tool_type == "plugin"]
        assert len(plugin_tools) == 1, "plugin 工具应被重建为 1 个"

    def test_delete_by_agent_tool_type_filter(self, session):
        tenant = "t1"
        _make_agent(session, tenant)
        session.add(AgentTool(
            id="at-plugin", tenant_id=tenant, agent_id="a1",
            tool_type="plugin", config={"plugin_id": "p1"}, name="wx",
        ))
        session.add(AgentTool(
            id="at-kb", tenant_id=tenant, agent_id="a1",
            tool_type="knowledge", config={"knowledge_base_id": "kb1"}, name="kb",
        ))
        session.commit()

        repo = AgentService(session, tenant).tool_repo
        repo.delete_by_agent("a1", tool_type="plugin")

        remaining = session.query(AgentTool).filter(
            AgentTool.agent_id == "a1"
        ).all()
        assert {t.tool_type for t in remaining} == {"knowledge"}


# ── M1-3 / M1-4：配置加密、脱敏、删除、required 校验 ────────────────────────


class TestPluginConfigEncryption:
    def test_encrypts_at_rest_and_masks_in_response(self, session, fernet):
        tenant = "t1"
        _make_plugin(session, tenant)
        svc = PluginService(session, tenant)

        svc.update_config("p1", PluginConfigUpdateRequest(items=[
            PluginConfigItem(name="api_key", value="sk-super-secret"),
            PluginConfigItem(name="base_url", value="https://api.example.com"),
        ]))

        # 回显：敏感值不回显（value=None + has_value=True），非敏感项回显真实值
        resp = svc.get_config("p1")
        by_name = {i.name: i for i in resp.items}
        assert by_name["api_key"].value is None
        assert by_name["api_key"].has_value is True
        assert by_name["base_url"].value == "https://api.example.com"
        assert by_name["base_url"].has_value is True

        # 运行时：解密得到真实值
        loaded = svc._load_config_dict("p1")
        assert loaded["api_key"] == "sk-super-secret"
        assert loaded["base_url"] == "https://api.example.com"

        # 落库：明文不在库，密文在库
        row = session.query(PluginConfig).filter(
            PluginConfig.plugin_id == "p1", PluginConfig.name == "api_key"
        ).first()
        assert row.value_encrypted is not None
        assert row.value == "********"

    def test_remove_deletes_config_item(self, session, fernet):
        tenant = "t1"
        _make_plugin(session, tenant)
        svc = PluginService(session, tenant)

        svc.update_config("p1", PluginConfigUpdateRequest(items=[
            PluginConfigItem(name="base_url", value="https://api.example.com"),
            PluginConfigItem(name="api_key", value="sk-x"),
        ]))
        # 删除 base_url（P1-C1：此前无法删除）
        svc.update_config("p1", PluginConfigUpdateRequest(
            items=[PluginConfigItem(name="api_key", value="sk-y")],
            remove=["base_url"],
        ))

        resp = svc.get_config("p1")
        names = {i.name for i in resp.items}
        assert names == {"api_key"}, "base_url 应已被删除"
        assert svc._load_config_dict("p1")["api_key"] == "sk-y"

    def test_required_validation_enforced(self, session, fernet):
        tenant = "t1"
        _make_plugin(session, tenant)
        plugin = session.get(Plugin, "p1")
        plugin.config_schema = {"required": ["api_key"]}
        session.flush()

        svc = PluginService(session, tenant)
        # 缺少必填项 -> 应抛异常且不写入
        with pytest.raises(ValidationException, match="缺少必填配置项"):
            svc.update_config("p1", PluginConfigUpdateRequest(items=[
                PluginConfigItem(name="base_url", value="https://x"),
            ]))
        # 提供必填项 -> 通过
        svc.update_config("p1", PluginConfigUpdateRequest(items=[
            PluginConfigItem(name="api_key", value="sk-x"),
        ]))
        assert svc._load_config_dict("p1")["api_key"] == "sk-x"

    def test_none_value_preserves_existing_secret(self, session, fernet):
        tenant = "t1"
        _make_plugin(session, tenant)
        svc = PluginService(session, tenant)
        svc.update_config("p1", PluginConfigUpdateRequest(items=[
            PluginConfigItem(name="api_key", value="sk-orig"),
        ]))
        # 敏感项回显为 null；用户保存时传回 null（未改动）-> 既有凭据不得被覆盖
        svc.update_config("p1", PluginConfigUpdateRequest(items=[
            PluginConfigItem(name="api_key", value=None),
        ]))
        assert svc._load_config_dict("p1")["api_key"] == "sk-orig"


# ── M1-5：端点入参 schema 接入工具参数 ───────────────────────────────────────


class TestBuildArgsSchema:
    def test_builds_model_from_properties(self):
        schema = {
            "type": "object",
            "properties": {
                "city": {"type": "string"},
                "top_k": {"type": "integer"},
            },
            "required": ["city"],
        }
        model = _build_args_schema(schema)
        assert "city" in model.model_fields
        assert "top_k" in model.model_fields
        # required 字段无默认值
        assert model.model_fields["city"].is_required()
        # 可选字段有默认值 None
        assert not model.model_fields["top_k"].is_required()

    def test_unknown_type_falls_back_to_str(self):
        model = _build_args_schema({
            "properties": {"x": {"type": "weird"}}, "required": ["x"],
        })
        assert model.model_fields["x"].annotation is str


class TestPluginToolArgsSchemaWiring:
    def test_tool_gets_args_schema_when_endpoint_has_schema(self, session, fernet):
        tenant = "t1"
        agent = _make_agent(session, tenant)
        _make_plugin(session, tenant)
        # 端点声明入参 schema
        ep = session.get(PluginEndpoint, "e1")
        ep.request_body_schema = {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        }
        # 提供运行所需配置
        session.add(PluginConfig(
            plugin_id="p1", tenant_id=tenant, name="base_url",
            value="https://api.example.com", value_encrypted="x",
        ))
        session.add(AgentTool(
            id="at-plugin", tenant_id=tenant, agent_id="a1",
            tool_type="plugin", config={"plugin_id": "p1", "endpoint": "/v1/x"},
            name="wx", is_enabled=True,
        ))
        session.commit()

        svc = AgentService(session, tenant)
        tools = svc._build_langchain_tools(agent)
        assert len(tools) == 1
        tool = tools[0]
        assert tool.args_schema is not None, "应注入端点入参 schema"
        assert "参数" in tool.description, "描述应提示参数"

    def test_tool_falls_back_to_query_when_no_schema(self, session, fernet):
        tenant = "t1"
        agent = _make_agent(session, tenant)
        _make_plugin(session, tenant)
        ep = session.get(PluginEndpoint, "e1")
        ep.request_body_schema = None
        session.add(PluginConfig(
            plugin_id="p1", tenant_id=tenant, name="base_url",
            value="https://api.example.com", value_encrypted="x",
        ))
        session.add(AgentTool(
            id="at-plugin", tenant_id=tenant, agent_id="a1",
            tool_type="plugin", config={"plugin_id": "p1", "endpoint": "/v1/x"},
            name="wx", is_enabled=True,
        ))
        session.commit()

        svc = AgentService(session, tenant)
        tools = svc._build_langchain_tools(agent)
        assert len(tools) == 1
        # 无端点 schema 时退化为**单字段 query 参数**（不再是「无 args_schema 的裸字符串」）。
        # 旧契约下 args_schema 为 None，工具被驱动时入参只能是位置字符串，模型无从知道
        # 该往哪个键里放内容；声明成结构化单字段后模型侧才能看到 query。
        assert tools[0].args_schema is not None, "无 schema 也应给出单字段 query 契约"
        assert list(tools[0].args_schema.model_fields) == ["query"]


class TestToolsAreStructuredForNativeToolCalling:
    """回归守卫：工具必须是 StructuredTool，且提示词可装配。

    历史缺陷（2026-09-15 定位）：工具用 ``langchain_core.tools.Tool`` 构建（单入参，
    任何输入都被折叠成一个**位置参数**），却被多字段 ``args_schema`` 的插件端点驱动，
    且执行器用文本 ReAct（``create_react_agent``）。三者叠加导致：
    ① ``create_react_agent`` 因提示词缺 ``{tool_names}`` 直接 ``ValueError``；
    ② 即便补上，字符串入参也会被塞进第一个形参（闭包用的 ``_plugin``），工具不执行；
    ③ dict 入参则抛 ``Too many arguments to single-input tool``。
    """

    def _tools(self, session, tenant):
        from app.models.plugin import PluginConfig
        from app.models.agent_tool import AgentTool
        from app.services.agent import AgentService

        agent = _make_agent(session, tenant)
        _make_plugin(session, tenant)
        ep = session.get(PluginEndpoint, "e1")
        ep.request_body_schema = {
            "type": "object",
            "properties": {
                "q": {"type": "string"},
                "sort": {"type": "string"},
                "per_page": {"type": "integer"},
            },
            "required": ["q"],
        }
        session.add(PluginConfig(
            plugin_id="p1", tenant_id=tenant, name="base_url",
            value="https://api.example.com", value_encrypted="x",
        ))
        session.add(AgentTool(
            id="at-plugin", tenant_id=tenant, agent_id="a1",
            tool_type="plugin", config={"plugin_id": "p1", "endpoint": "/v1/x"},
            name="wx", is_enabled=True,
        ))
        session.commit()
        return AgentService(session, tenant)._build_langchain_tools(agent)

    def test_tool_is_structured_tool_not_single_input_tool(self, session, fernet):
        from langchain_core.tools import StructuredTool

        tools = self._tools(session, "t1")
        assert len(tools) == 1
        assert isinstance(tools[0], StructuredTool), (
            "必须是 StructuredTool：单入参 Tool 无法承载多字段 args_schema"
        )

    def test_multi_field_args_expand_to_kwargs(self, session, fernet):
        """多字段入参必须按关键字展开，而不是塌缩成一个位置参数。"""
        from app.utils import plugin_executor

        recorded = {}

        def _fake(**kwargs):
            recorded["params"] = kwargs.get("params")
            return {"success": True, "data": {"ok": True}}

        monkey = plugin_executor.execute_plugin_call
        plugin_executor.execute_plugin_call = _fake
        try:
            tools = self._tools(session, "t1")
            # StructuredTool 的正确调用形态是 dict（原生工具调用即回传 dict）
            tools[0].invoke({"q": "vector db", "sort": "stars"})
        finally:
            plugin_executor.execute_plugin_call = monkey

        assert recorded["params"] == {"q": "vector db", "sort": "stars"}

    def test_executor_builds_without_missing_variable_error(self, session, fernet):
        """装配必须成功：不得再出现 ``Prompt missing required variables``。

        旧实现用 ``create_react_agent``，它会强制校验提示词同时含
        ``tools``/``tool_names``/``agent_scratchpad``；项目里的模板缺 ``tool_names``，
        于是**任何绑定工具的 Agent 首次对话必崩**。此处只做装配（不发起网络请求），
        用真实 ``ChatOpenAI`` 是为了让 ``bind_tools`` 走真实分支。
        """
        from langchain_openai import ChatOpenAI

        from app.services.agent import AgentService

        tools = self._tools(session, "t1")
        svc = AgentService(session, "t1")
        agent = svc.get_agent("a1")
        llm = ChatOpenAI(model="gpt-4o-mini", api_key="sk-test", base_url="http://127.0.0.1:1/v1")
        executor = svc._build_tool_agent_executor(agent, tools, llm=llm)
        assert executor is not None

    def test_executor_rejects_model_without_tool_calling(self, session, fernet):
        """模型不支持 function calling 时给出明确错误，而不是运行到一半才崩。"""
        from app.services.agent import AgentAssemblyError, AgentService

        class _NoTools:
            """既无 bind_tools 的替身。"""

        # 先建好 agent（同时验证工具构建正常），再单独验证装配期的模型能力检查
        self._tools(session, "t1")
        svc = AgentService(session, "t1")
        agent = svc.get_agent("a1")
        with pytest.raises(AgentAssemblyError) as exc:
            svc._build_tool_agent_executor(agent, [], llm=_NoTools())
        assert "不支持工具调用" in str(exc.value)
