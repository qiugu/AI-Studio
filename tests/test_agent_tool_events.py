"""Agent 默认知识库能力与工具生命周期事件回归测试。"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import app.services.agent as agent_module
from app.models.knowledge_base import KnowledgeBase


class _Query:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def all(self):
        return self.rows


class _Db:
    def __init__(self, rows):
        self.rows = rows

    def query(self, model):
        assert model is KnowledgeBase
        return _Query(self.rows)


def _collect(gen):
    async def drain():
        return [item async for item in gen]

    return asyncio.run(drain())


async def _events(*events):
    for event in events:
        yield event


def test_agent_without_explicit_knowledge_tool_gets_indexed_tenant_knowledge():
    service = agent_module.AgentService(
        db=_Db([
            SimpleNamespace(id="kb-1", name="产品手册", chunk_count=12, deleted_at=None),
            SimpleNamespace(id="kb-empty", name="空知识库", chunk_count=0, deleted_at=None),
        ]),
        tenant_id="tenant-1",
    )
    agent = SimpleNamespace(tools=[])

    tools = service._effective_agent_tools(agent)

    assert [(tool.tool_type, tool.config["knowledge_base_id"]) for tool in tools] == [
        ("knowledge", "kb-1"),
    ]
    assert tools[0].name == "knowledge-kb-1"


def test_tool_lifecycle_events_include_bounded_observation_payloads():
    executor = SimpleNamespace(
        astream_events=lambda inputs, version: _events(
            {
                "event": "on_tool_start",
                "name": "knowledge-kb-1",
                "run_id": "run-1",
                "data": {"input": {"query": "如何发布"}},
            },
            {
                "event": "on_tool_end",
                "name": "knowledge-kb-1",
                "run_id": "run-1",
                "data": {"output": "发布步骤"},
            },
        )
    )

    service = agent_module.AgentService(db=MagicMock(), tenant_id="tenant-1")
    events = _collect(service._iter_tool_agent_output(executor, {}))

    assert events[0] == {
        "type": "tool_start",
        "call_id": "run-1",
        "tool": "knowledge-kb-1",
        "input": {"query": "如何发布"},
        "status": "running",
    }
    assert events[1] == {
        "type": "tool_end",
        "call_id": "run-1",
        "tool": "knowledge-kb-1",
        "output": "发布步骤",
        "status": "success",
    }
