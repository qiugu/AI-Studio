"""Agent 流式输出中 citations 事件的时序测试（不连 LLM / Qdrant / MySQL）

验证：
* 知识库工具完成后、生成正文前，推送 ``citations`` 事件；
* 非知识库工具（collector 无新引用）不产生 citations 事件；
* 多次工具调用产生多个 citations 事件，且编号不重叠（去重生效）。

``_iter_tool_agent_output`` 是 **async 生成器**，测试须用 ``async for`` 消费，
切忌直接 ``list()``（会得到 ``async_generator`` 不可迭代的 TypeError）。
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest

import app.services.agent as agent_module
from app.utils.citation import CitationCollector


def _res(cid: str) -> Dict[str, Any]:
    return {
        "id": cid,
        "content": f"content-{cid}",
        "doc_id": "d1",
        "doc_name": "手册.pdf",
        "chunk_index": 0,
        "source_page": 1,
        "source_page_end": 1,
        "heading_path": None,
        "heading_path_mixed": False,
        "score": 0.9,
        # 检索层装配产物：含上下文窗口但**不含 [n] 角标**（角标由工具统一前缀）。
        "llm_content": f"content-{cid}",
        "context_header": None,
        "context_expanded": False,
    }


async def _drain(gen):
    """消费 async 生成器，收集为列表。"""
    return [item async for item in gen]


def _collect(gen) -> List[Dict[str, Any]]:
    return asyncio.run(_drain(gen))


async def _fake_executor(*events):
    for ev in events:
        yield ev


def _make_executor(events: List[Dict[str, Any]]) -> SimpleNamespace:
    return SimpleNamespace(
        astream_events=lambda inputs, version: _fake_executor(*events)
    )


def _svc() -> agent_module.AgentService:
    return agent_module.AgentService(db=MagicMock(), tenant_id="t")


class TestCitationsEventOrdering:
    def test_citations_event_appears_before_first_message(self):
        collector = CitationCollector()
        # 预登记一次命中（等价于工具在 on_tool_end 前已执行完毕并登记）
        collector.register([_res("c1")], tool_name="kb", query="q")
        executor = _make_executor(
            [
                {"event": "on_tool_end", "name": "kb"},
                {"event": "on_chat_model_stream", "data": {"chunk": SimpleNamespace(content="答案")}},
                {"event": "on_chat_model_end", "data": {"output": SimpleNamespace(usage_metadata={})}},
            ]
        )
        sequence = _collect(_svc()._iter_tool_agent_output(executor, {}, collector=collector))
        types = [item["type"] for item in sequence]
        assert "citations" in types
        # 底层生成器以 "content" 类型产出逐字文本（chat_stream 再包成 SSE message）
        assert "content" in types
        # 来源必须先于正文到达，前端才能边生成边展示来源面板
        assert types.index("citations") < types.index("content")
        cit = next(item for item in sequence if item["type"] == "citations")
        assert cit["citations"][0]["chunk_id"] == "c1"

    def test_no_citations_when_collector_empty(self):
        """非知识库工具：on_tool_end 不产生新引用，不发 citations 事件"""
        executor = _make_executor(
            [
                {"event": "on_tool_end", "name": "api"},
                {"event": "on_chat_model_stream", "data": {"chunk": SimpleNamespace(content="x")}},
                {"event": "on_chat_model_end", "data": {"output": SimpleNamespace(usage_metadata={})}},
            ]
        )
        sequence = _collect(_svc()._iter_tool_agent_output(executor, {}, collector=CitationCollector()))
        assert not any(item["type"] == "citations" for item in sequence)

    def test_multiple_tool_calls_emit_multiple_citations_events(self):
        """多次工具调用 → 多个 citations 事件，且编号增量推送、不重叠（去重生效）

        真实执行中，知识库工具在自己的 ``on_tool_end`` **之前**完成检索并登记引用；
        因此用「边 yield 边登记」的假执行器来忠实模拟，而非把所有引用预先登记好
        （后者会让它们在同一时刻全部发出，测不到增量推送）。
        """
        collector = CitationCollector()

        async def _exec_with_register():
            # 第一次工具召回 c1,c2（编号 1,2）
            collector.register([_res("c1"), _res("c2")], tool_name="kb", query="q1")
            yield {"event": "on_tool_end", "name": "kb"}
            # 第二次召回 c1（去重沿用 1）+ 新块 c3（编号 3）
            collector.register([_res("c1"), _res("c3")], tool_name="kb", query="q2")
            yield {"event": "on_tool_end", "name": "kb"}
            yield {
                "event": "on_chat_model_stream",
                "data": {"chunk": SimpleNamespace(content="a")},
            }

        executor = SimpleNamespace(astream_events=lambda inputs, version: _exec_with_register())
        sequence = _collect(_svc()._iter_tool_agent_output(executor, {}, collector=collector))

        cit_events = [item for item in sequence if item["type"] == "citations"]
        assert len(cit_events) == 2
        # 第一次含 c1,c2（marker 1,2），第二次仅含新增的 c3（marker 3）
        assert [x["marker"] for x in cit_events[0]["citations"]] == [1, 2]
        assert [x["marker"] for x in cit_events[1]["citations"]] == [3]


class TestChatStreamCitationsForwarding:
    """``chat_stream`` 必须透传底层 citations 事件，并在 done 事件携带完整引用

    回归保护：曾有实现用 ``if item["type"] != "content": continue`` 把 citations
    事件整体丢弃，并漏给 done 事件附 citations——导致前端在流式对话中收不到来源、
    引用也无法落库。本类用桩依赖驱动 ``chat_stream`` 全链路（不连 LLM / 工具 / DB）。
    """

    def test_chat_stream_forwards_citations_and_attaches_to_done(self, monkeypatch):
        svc = _svc()

        # 桩 Collector：任何增量/快照都返回已知引用，避免构造真实工具。
        # 注意 chat_stream 内部 ``CitationCollector()`` 解析的是模块级名字，
        # 故此处 monkeypatch 的是 ``agent_module.CitationCollector``。
        class _StubCollector:
            def register(self, *a, **k):
                return [1]

            def take_new_since(self, i):
                return ([{"marker": 1, "chunk_id": "c1", "tool_name": "kb"}], 1)

            def snapshot(self):
                return [{"marker": 1, "chunk_id": "c1", "tool_name": "kb"}]

        monkeypatch.setattr(agent_module, "CitationCollector", _StubCollector)

        # 其余依赖一律以桩顶替，使 chat_stream 走「有工具」分支
        svc.get_agent = lambda *a, **k: SimpleNamespace(
            system_prompt=None,
            model_id="m",
            tools=[SimpleNamespace(is_enabled=True, tool_type="knowledge", name="kb",
                                   description=None, config={"knowledge_base_id": "kb-x"})],
        )
        svc._build_llm_client = lambda *a, **k: MagicMock()
        svc._build_chat_history = lambda *a, **k: []
        svc.token_usage_service = MagicMock(record_usage=MagicMock())
        svc._record_model_call = MagicMock()
        svc.db = MagicMock(commit=MagicMock()
        )
        # 返回非空工具列表，确保进入 _iter_tool_agent_output 路径
        svc._build_langchain_tools = lambda agent, collector=None: [
            SimpleNamespace(name="kb", func=lambda q: "x")
        ]

        async def _fake_exec(*ev):
            for e in ev:
                yield e

        svc._build_tool_agent_executor = lambda *a, **k: SimpleNamespace(
            astream_events=lambda inputs, version: _fake_exec(
                {"event": "on_tool_end", "name": "kb"},
                {"event": "on_chat_model_stream",
                 "data": {"chunk": SimpleNamespace(content="答案")}},
                {"event": "on_chat_model_end",
                 "data": {"output": SimpleNamespace(usage_metadata={})}},
            )
        )

        out = _collect(
            svc.chat_stream(agent_id="a", message="q", conversation_id=None, user_id="u")
        )
        types = [i["type"] for i in out]
        assert "citations" in types
        assert "message" in types
        # 来源先于正文
        assert types.index("citations") < types.index("message")
        # done 事件冗余携带完整引用，供落库与前端兜底
        done = next(i for i in out if i["type"] == "done")
        assert done["citations"][0]["chunk_id"] == "c1"
