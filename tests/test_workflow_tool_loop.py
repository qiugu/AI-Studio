import asyncio
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from app.core.exceptions import ValidationException
from app.services.workflow_engine import WorkflowEngine


class _FakeTool:
    name = "weather"

    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    async def ainvoke(self, args):
        self.calls.append(args)
        if self.error:
            raise self.error
        return self.result


class _FakeBoundModel:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def bind_tools(self, tools):
        self.tools = tools
        return self

    async def ainvoke(self, messages):
        self.calls.append(list(messages))
        return self.responses.pop(0)


def test_workflow_llm_replays_tool_result_until_final_answer():
    tool = _FakeTool(result={"temperature": 26})
    model = _FakeBoundModel([
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "weather",
                    "args": {"city": "北京"},
                    "id": "call-weather-1",
                    "type": "tool_call",
                }
            ],
        ),
        AIMessage(content="北京今天晴朗，气温 26 度。"),
    ])
    engine = WorkflowEngine.__new__(WorkflowEngine)

    final_text, trace = asyncio.run(
        engine._invoke_llm_with_tools(
            model,
            "查询北京天气",
            [tool],
            max_rounds=3,
        )
    )

    assert final_text == "北京今天晴朗，气温 26 度。"
    assert tool.calls == [{"city": "北京"}]
    assert trace == [{"round": 1, "tool_name": "weather", "status": "success"}]
    assert isinstance(model.calls[1][2], ToolMessage)
    assert model.calls[1][2].tool_call_id == "call-weather-1"
    assert '"temperature": 26' in model.calls[1][2].content


def test_workflow_llm_stops_when_tool_round_limit_is_reached():
    tool = _FakeTool(result="still working")
    model = _FakeBoundModel([
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "weather",
                    "args": {"city": "北京"},
                    "id": "call-weather-1",
                    "type": "tool_call",
                }
            ],
        ),
    ])
    engine = WorkflowEngine.__new__(WorkflowEngine)

    with pytest.raises(ValidationException, match="最大轮数"):
        asyncio.run(
            engine._invoke_llm_with_tools(
                model,
                "查询北京天气",
                [tool],
                max_rounds=1,
            )
        )


def test_workflow_llm_returns_tool_error_as_observation():
    tool = _FakeTool(error=RuntimeError("upstream unavailable"))
    model = _FakeBoundModel([
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "weather",
                    "args": {"city": "北京"},
                    "id": "call-weather-1",
                    "type": "tool_call",
                }
            ],
        ),
        AIMessage(content="天气服务暂时不可用。"),
    ])
    engine = WorkflowEngine.__new__(WorkflowEngine)

    final_text, trace = asyncio.run(
        engine._invoke_llm_with_tools(
            model,
            "查询北京天气",
            [tool],
            max_rounds=2,
        )
    )

    assert final_text == "天气服务暂时不可用。"
    assert trace == [{"round": 1, "tool_name": "weather", "status": "error"}]
    assert "工具调用失败" in model.calls[1][2].content


def test_workflow_llm_emits_tool_lifecycle_events():
    tool = _FakeTool(result={"temperature": 26})
    model = _FakeBoundModel([
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "weather",
                    "args": {"city": "北京"},
                    "id": "call-weather-1",
                    "type": "tool_call",
                }
            ],
        ),
        AIMessage(content="完成"),
    ])
    events = []
    engine = WorkflowEngine.__new__(WorkflowEngine)

    asyncio.run(
        engine._invoke_llm_with_tools(
            model,
            "查询北京天气",
            [tool],
            max_rounds=2,
            tool_event_callback=events.append,
        )
    )

    assert events == [
        {"type": "tool_started", "tool_name": "weather", "round": 1},
        {
            "type": "tool_completed",
            "tool_name": "weather",
            "round": 1,
            "status": "success",
        },
    ]


def test_llm_node_uses_bound_tools_and_returns_final_answer(monkeypatch):
    tool = _FakeTool(result={"temperature": 26})
    model_client = _FakeBoundModel([
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "weather",
                    "args": {"city": "北京"},
                    "id": "call-weather-1",
                    "type": "tool_call",
                }
            ],
        ),
        AIMessage(content="北京今天晴朗。"),
    ])
    model_record = SimpleNamespace(
        id="model-1",
        name="gpt-test",
        status=True,
        model_type="chat",
        provider_id="provider-1",
        max_output_tokens=4096,
    )
    provider_record = SimpleNamespace(
        status=True,
        provider_type="openai",
        api_key_encrypted="encrypted",
        api_base_url=None,
    )

    class _Query:
        def __init__(self, value):
            self.value = value

        def filter(self, *_args):
            return self

        def first(self):
            return self.value

    class _DB:
        def query(self, model_class):
            value = provider_record if model_class.__name__ == "AIProvider" else model_record
            return _Query(value)

    class _ToolService:
        def __init__(self, db, tenant_id, actor=None):
            assert tenant_id == "tenant-1"

        def build_langchain_tools_for_bindings(self, bindings):
            assert bindings[0]["name"] == "天气查询"
            return [tool]

    monkeypatch.setattr("app.services.agent.AgentService", _ToolService, raising=False)
    monkeypatch.setattr("app.utils.encryption.decrypt", lambda _value: "api-key")
    monkeypatch.setattr("app.utils.llm.build_chat_model", lambda **_kwargs: model_client)

    engine = WorkflowEngine.__new__(WorkflowEngine)
    engine.db = _DB()
    engine.tenant_id = "tenant-1"
    engine.actor = None
    node = SimpleNamespace(
        id="llm-1",
        config={
            "model_id": "model-1",
            "prompt_template": "请查询北京天气",
            "output_variable": "answer",
            "tool_bindings": [
                {
                    "name": "天气查询",
                    "tool_type": "plugin",
                    "config": {"plugin_id": "plugin-1", "endpoint_id": "endpoint-1"},
                }
            ],
            "max_tool_rounds": 3,
        },
    )

    output = asyncio.run(engine._execute_llm_node(node, {}))

    assert output == {"answer": "北京今天晴朗。", "tool_call_count": 1}
