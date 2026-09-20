"""Agent 知识库工具的绑定与失败处理契约

本文件覆盖两类**静默失效**风险：

1. **串库**：一个 Agent 绑定多个知识库工具时，每个工具必须查询**自己**配置的知识库。
   若 ``kb_id`` / ``top_k`` 以闭包晚绑定方式引用外层循环变量，所有工具都会查询循环中
   最后一个知识库——不报错、不告警，线上表现与「该库没有相关内容」完全一致。

2. **故障被当成事实**：LangChain 的 ``Tool`` 默认不吞异常，抛出会中断 ReAct 执行；
   而降级（集合缺失 / Qdrant 不可用）若返回与「无结果」相同的文案，模型会据此向用户
   断言「知识库中不存在该内容」——把基础设施故障说成业务事实。

全部依赖以替身注入：不连数据库、不连 Qdrant、不加载模型。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import app.services.agent as agent_module
from app.services.knowledge import SearchOutcome
from app.utils.citation import CitationCollector


def _result(cid: str) -> dict:
    """命中块替身：含装配层三键，供 citations 测试构造引用对象"""
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
        # 检索层装配产物：含上下文窗口但**不含 [n] 角标**——角标由 Agent 工具
        # 在 collector 非空时统一前缀，避免检索层与工具重复编号。
        "llm_content": f"content-{cid}",
        "context_header": None,
        "context_expanded": False,
    }


class _RecordingKnowledgeService:
    """记录每次检索的实际入参，并可注入返回/异常以覆盖失败路径"""

    calls: list[dict] = []
    outcome: SearchOutcome | None = None
    error: Exception | None = None

    def __init__(self, db, tenant_id):
        self.db = db
        self.tenant_id = tenant_id

    def search_with_diagnostics(self, *, kb_id, query, top_k) -> SearchOutcome:
        type(self).calls.append({"kb_id": kb_id, "query": query, "top_k": top_k})
        if type(self).error is not None:
            raise type(self).error
        if type(self).outcome is not None:
            return type(self).outcome
        return SearchOutcome(
            results=[{"content": f"来自 {kb_id} 的片段"}], collection=f"kb_{kb_id}"
        )


@pytest.fixture(autouse=True)
def _patch_knowledge_service(monkeypatch):
    _RecordingKnowledgeService.calls = []
    _RecordingKnowledgeService.outcome = None
    _RecordingKnowledgeService.error = None
    monkeypatch.setattr(agent_module, "KnowledgeBaseService", _RecordingKnowledgeService)
    yield
    _RecordingKnowledgeService.calls = []


def _build_tools(bindings):
    """按 ``[(工具名, config)]`` 构造工具列表"""
    service = agent_module.AgentService(db=MagicMock(), tenant_id="tenant-1")
    agent = SimpleNamespace(
        tools=[
            SimpleNamespace(
                is_enabled=True,
                tool_type="knowledge",
                name=name,
                description=None,
                config=config,
            )
            for name, config in bindings
        ]
    )
    return service._build_langchain_tools(agent)


class TestKnowledgeToolBinding:
    def test_each_tool_queries_its_own_knowledge_base(self):
        """工具与知识库必须一一对应（P1-B 回归）"""
        tools = _build_tools(
            [
                ("kb_alpha", {"knowledge_base_id": "kb-alpha", "top_k": 3}),
                ("kb_beta", {"knowledge_base_id": "kb-beta", "top_k": 7}),
            ]
        )
        assert [tool.name for tool in tools] == ["kb_alpha", "kb_beta"]

        tools[0].func("查询")
        tools[1].func("查询")

        assert _RecordingKnowledgeService.calls == [
            {"kb_id": "kb-alpha", "query": "查询", "top_k": 3},
            {"kb_id": "kb-beta", "query": "查询", "top_k": 7},
        ]

    def test_first_tool_does_not_fall_through_to_last_base(self):
        """反向断言：闭包晚绑定的典型表现是「都查最后一个库」

        只调用第一个工具即可暴露问题——若实现是晚绑定，此处会命中 kb-beta。
        """
        tools = _build_tools(
            [
                ("kb_alpha", {"knowledge_base_id": "kb-alpha"}),
                ("kb_beta", {"knowledge_base_id": "kb-beta"}),
            ]
        )
        tools[0].func("x")
        assert _RecordingKnowledgeService.calls[0]["kb_id"] == "kb-alpha"

    def test_top_k_defaults_to_five_when_absent(self):
        tools = _build_tools(
            [
                ("kb_alpha", {"knowledge_base_id": "kb-alpha"}),
                ("kb_beta", {"knowledge_base_id": "kb-beta", "top_k": 9}),
            ]
        )
        tools[0].func("x")
        tools[1].func("x")
        assert [call["top_k"] for call in _RecordingKnowledgeService.calls] == [5, 9]

    def test_disabled_tool_is_skipped(self):
        service = agent_module.AgentService(db=MagicMock(), tenant_id="tenant-1")
        agent = SimpleNamespace(
            tools=[
                SimpleNamespace(
                    is_enabled=False,
                    tool_type="knowledge",
                    name="kb_off",
                    description=None,
                    config={"knowledge_base_id": "kb-alpha"},
                )
            ]
        )
        assert service._build_langchain_tools(agent) == []


class TestKnowledgeToolFailureHandling:
    def test_successful_search_returns_concatenated_content(self):
        tools = _build_tools([("kb_alpha", {"knowledge_base_id": "kb-alpha"})])
        assert tools[0].func("x") == "来自 kb-alpha 的片段"

    def test_empty_result_returns_not_found(self):
        _RecordingKnowledgeService.outcome = SearchOutcome(results=[])
        tools = _build_tools([("kb_alpha", {"knowledge_base_id": "kb-alpha"})])
        assert tools[0].func("x") == "未找到相关知识"

    def test_exception_is_converted_to_readable_text(self):
        """工具异常必须被吞掉并转为可读结果（P2-F）

        否则 LangChain 会中断 ReAct 执行，且把内部异常文本暴露给模型。
        """
        _RecordingKnowledgeService.error = RuntimeError("boom: internal detail")
        tools = _build_tools([("kb_alpha", {"knowledge_base_id": "kb-alpha"})])

        output = tools[0].func("x")  # 不抛异常即为通过
        assert "知识库检索失败" in output
        assert "RuntimeError" in output
        # 不泄漏原始异常消息
        assert "boom" not in output

    def test_degraded_result_is_not_reported_as_absence(self):
        """降级时不得回「未找到相关知识」——那会把故障说成业务事实"""
        _RecordingKnowledgeService.outcome = SearchOutcome(
            results=[], degraded=True, reason="collection_not_found"
        )
        tools = _build_tools([("kb_alpha", {"knowledge_base_id": "kb-alpha"})])

        output = tools[0].func("x")
        assert "未生效" in output
        assert "collection_not_found" in output
        assert "未找到相关知识" not in output


class TestKnowledgeToolCitations:
    """知识库工具命中时给文本加 ``[n]`` 前缀并登记引用（D1/D3）"""

    def _collector_tools(self, bindings, collector):
        service = agent_module.AgentService(db=MagicMock(), tenant_id="tenant-1")
        agent = SimpleNamespace(
            tools=[
                SimpleNamespace(
                    is_enabled=True,
                    tool_type="knowledge",
                    name=name,
                    description=None,
                    config=config,
                )
                for name, config in bindings
            ]
        )
        return service._build_langchain_tools(agent, collector)

    def test_result_blocks_are_prefixed_with_markers(self):
        collector = CitationCollector()
        _RecordingKnowledgeService.outcome = SearchOutcome(
            results=[_result("c1"), _result("c2")]
        )
        tools = self._collector_tools([("kb", {"knowledge_base_id": "kb-x"})], collector)
        out = tools[0].func("q")
        # 每个命中块带 [n] 前缀，编号与 collector 一致
        assert "[1] content-c1" in out
        assert "[2] content-c2" in out
        # 引用对象已登记且 chunk_id 正确
        snap = collector.snapshot()
        assert [x["chunk_id"] for x in snap] == ["c1", "c2"]
        assert [x["marker"] for x in snap] == [1, 2]

    def test_no_collector_returns_plain_content(self):
        """工作流节点复用本工具时 collector=None，不应给文本加前缀"""
        _RecordingKnowledgeService.outcome = SearchOutcome(results=[_result("c1")])
        tools = agent_module.AgentService(
            db=MagicMock(), tenant_id="t"
        )._build_langchain_tools(
            SimpleNamespace(
                tools=[
                    SimpleNamespace(
                        is_enabled=True,
                        tool_type="knowledge",
                        name="kb",
                        description=None,
                        config={"knowledge_base_id": "kb-x"},
                    )
                ]
            )
        )
        assert tools[0].func("q") == "content-c1"

    def test_registration_dedups_across_calls(self):
        """同一块跨工具调用召回时，编号沿用首次、不新增（R3）"""
        collector = CitationCollector()
        _RecordingKnowledgeService.outcome = SearchOutcome(results=[_result("c1"), _result("c2")])
        tools = self._collector_tools([("kb", {"knowledge_base_id": "kb-x"})], collector)
        tools[0].func("q1")
        # 第二次召回 c1（去重）+ c3（新）
        _RecordingKnowledgeService.outcome = SearchOutcome(results=[_result("c1"), _result("c3")])
        tools[0].func("q2")
        snap = collector.snapshot()
        assert [x["marker"] for x in snap] == [1, 2, 3]
        assert [x["chunk_id"] for x in snap] == ["c1", "c2", "c3"]
