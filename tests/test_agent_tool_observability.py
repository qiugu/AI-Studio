"""Agent 工具调用异常时也必须留下可观测的 assistant 消息。"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import app.api.agent as agent_api
from app.schemas.conversation import ChatRequest


def test_stream_persists_partial_tool_trace_when_agent_fails_after_tool_start(monkeypatch):
    calls = []

    class FakeAgentService:
        def __init__(self, **_kwargs):
            pass

        def get_agent(self, _agent_id):
            return SimpleNamespace(id="agent-1")

        async def chat_stream(self, **_kwargs):
            yield {
                "type": "tool_start",
                "call_id": "run-1",
                "tool": "crm-search",
                "input": {"query": "客户"},
                "status": "running",
            }
            raise RuntimeError("模型在工具返回后中断")

    class FakeConversationService:
        def __init__(self, **_kwargs):
            pass

        def add_message(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace()

    monkeypatch.setattr(agent_api, "AgentService", FakeAgentService)
    monkeypatch.setattr(agent_api, "ConversationService", FakeConversationService)
    monkeypatch.setattr(agent_api, "_authorize_agent", lambda *_args: None)

    user = SimpleNamespace(id="user-1", tenant_id="tenant-1")
    response = asyncio.run(
        agent_api.chat_stream(
            "agent-1",
            ChatRequest(message="查客户", conversation_id="conv-1"),
            db=MagicMock(),
            current_user=user,
        )
    )

    async def consume():
        return [chunk async for chunk in response.body_iterator]

    asyncio.run(consume())

    assistant_messages = [call for call in calls if call.get("role") == "assistant"]
    assert assistant_messages
    assert assistant_messages[-1]["tool_calls"] == [
        {
            "call_id": "run-1",
            "tool": "crm-search",
            "input": {"query": "客户"},
            "status": "running",
        }
    ]

def test_stream_persists_completed_tool_trace_on_normal_done(monkeypatch):
    calls = []

    class FakeAgentService:
        def __init__(self, **_kwargs):
            pass

        def get_agent(self, _agent_id):
            return SimpleNamespace(id="agent-1")

        async def chat_stream(self, **_kwargs):
            yield {
                "type": "tool_start",
                "call_id": "run-2",
                "tool": "crm-search",
                "input": {"query": "客户"},
                "status": "running",
            }
            yield {
                "type": "tool_end",
                "call_id": "run-2",
                "tool": "crm-search",
                "output": {"items": ["客户 A"]},
                "status": "success",
            }
            yield {"type": "message", "content": "已找到客户 A"}
            # Service 的 done 摘要可能只携带起始状态；API 层必须与已转发的
            # 完整生命周期合并，不能用 truthy 的 done 列表覆盖 tool_end。
            yield {
                "type": "done",
                "tool_calls": [
                    {
                        "call_id": "run-2",
                        "tool": "crm-search",
                        "input": {"query": "客户"},
                        "status": "running",
                    }
                ],
            }

    class FakeConversationService:
        def __init__(self, **_kwargs):
            pass

        def add_message(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace()

    monkeypatch.setattr(agent_api, "AgentService", FakeAgentService)
    monkeypatch.setattr(agent_api, "ConversationService", FakeConversationService)
    monkeypatch.setattr(agent_api, "_authorize_agent", lambda *_args: None)

    user = SimpleNamespace(id="user-1", tenant_id="tenant-1")
    response = asyncio.run(
        agent_api.chat_stream(
            "agent-1",
            ChatRequest(message="查客户", conversation_id="conv-1"),
            db=MagicMock(),
            current_user=user,
        )
    )

    async def consume():
        return [chunk async for chunk in response.body_iterator]

    asyncio.run(consume())

    assistant_messages = [call for call in calls if call.get("role") == "assistant"]
    assert assistant_messages[-1]["tool_calls"] == [
        {
            "call_id": "run-2",
            "tool": "crm-search",
            "input": {"query": "客户"},
            "output": {"items": ["客户 A"]},
            "status": "success",
        }
    ]
