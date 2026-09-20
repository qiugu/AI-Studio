"""引用收集器（请求级单实例）

负责把「知识库检索命中块」转换成「可被模型引用、可被前端溯源」的结构化引用对象，
并为其分配**单轮对话内唯一且稳定**的编号。

设计要点（见 docs/plan-citation-traceability.md §D2/D3）：

* 编号在单轮对话（单次 chat 请求）内从 1 起单调递增，跨多次工具调用延续；
* 以 ``chunk_id`` 去重：同一块被第二次召回时沿用首次编号，不新增；
* 纯逻辑、无 IO，便于单测（``tests/test_citation_collector.py``）。

为什么要单独成模块、不放进 ``agent.py``：编号分配、去重、内容截断都属于可独立
断言的纯逻辑，抽出来后单测不需要装配 Agent / 工具 / LLM，也不依赖 LangChain 的
闭包捕获细节。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

#: 命中块原文快照的最大字符数。仅当调用方显式传入（如 ``top_k > 20``）时生效，
#: 避免极端配置下 ``citations`` 体积失控。命中块原文是引用卡片的权威展示源，
#: 截断只会发生在大 ``top_k`` 场景，并打 ``content_truncated`` 标记由前端提示。
_MAX_CONTENT_CHARS = 1200


def _build_citation(
    result: Dict[str, Any],
    *,
    marker: int,
    kb_id: Optional[str],
    tool_name: str,
    query: str,
    max_content_chars: Optional[int],
) -> Dict[str, Any]:
    """从一条检索结果构造一个引用对象。

    字段来源见 docs/citation-traceability.md §5.1。``content`` 取命中块原文快照，
    ``llm_content`` / ``context_header`` / ``context_expanded`` 沿用检索层装配产物。
    """
    content = result.get("content") or ""
    if max_content_chars and len(content) > max_content_chars:
        content = content[:max_content_chars]
        content_truncated = True
    else:
        content_truncated = False
    return {
        "marker": marker,
        "chunk_id": result.get("id"),
        "doc_id": result.get("doc_id"),
        "doc_name": result.get("doc_name"),
        "kb_id": kb_id,
        "chunk_index": result.get("chunk_index"),
        "source_page": result.get("source_page"),
        "source_page_end": result.get("source_page_end"),
        "heading_path": result.get("heading_path"),
        "heading_path_mixed": result.get("heading_path_mixed"),
        # 块类型随引用一起快照：引用面板要按类型选择渲染方式（表格/代码按纯文本渲染
        # 会丢结构），而引用对象刻意只带**内容快照**、不回查数据库（见
        # docs/citation-traceability.md §5.1）——不回查就意味着不带上它，之后再也
        # 补不回来。存量引用对象没有该键，消费方按缺省 ``text`` 处理。
        "chunk_type": result.get("chunk_type"),
        "score": result.get("score"),
        "content": content,
        "content_truncated": content_truncated,
        "llm_content": result.get("llm_content"),
        "context_header": result.get("context_header"),
        "context_expanded": result.get("context_expanded"),
        "tool_name": tool_name,
        "query": query,
    }


class CitationCollector:
    """请求级引用收集器。

    用法：在 ``chat()`` 内创建单实例，经 ``_build_langchain_tools(agent, collector)``
    传给知识库工具；工具检索成功后调用 :meth:`register` 登记命中块，并拿到与
    ``results`` 对齐的编号列表用于给文本加 ``[n]`` 前缀。
    """

    def __init__(self) -> None:
        # 编号从 1 起；已登记的 chunk_id -> 首次分配的编号（去重表）
        self._citations: List[Dict[str, Any]] = []
        self._marker_by_chunk: Dict[Optional[str], int] = {}

    def register(
        self,
        results: List[Dict[str, Any]],
        *,
        tool_name: str,
        query: str,
        kb_id: Optional[str] = None,
        max_content_chars: Optional[int] = None,
    ) -> List[int]:
        """登记一批检索结果，返回与 ``results`` 对齐的编号列表。

        Args:
            results: ``KnowledgeBaseService.search_with_diagnostics().results``，
                每条含 ``id`` / ``content`` / ``doc_id`` / ``doc_name`` /
                ``chunk_index`` / ``source_page`` 等字段（见 ``knowledge.py`` 组装）。
            tool_name: 召回这些块的工具名（来自 ``agent_tool.name``）。
            query: 触发本次召回的查询文本。
            kb_id: 知识库 ID（用于前端区分多库来源）。
            max_content_chars: 命中块原文快照的最大字符数；``None`` 不截断。

        Returns:
            与 ``results`` 同序的编号列表。同一 ``chunk_id`` 复用首次编号（去重）。

        注意：``results`` 内部已由服务层按内容去重，因此单次调用内编号互不重复；
        跨调用复用靠 ``_marker_by_chunk`` 保证。
        """
        markers: List[int] = []
        for result in results:
            chunk_id = result.get("id")
            existing = self._marker_by_chunk.get(chunk_id)
            if existing is not None:
                markers.append(existing)
                continue
            marker = len(self._citations) + 1
            self._marker_by_chunk[chunk_id] = marker
            self._citations.append(
                _build_citation(
                    result,
                    marker=marker,
                    kb_id=kb_id,
                    tool_name=tool_name,
                    query=query,
                    max_content_chars=max_content_chars,
                )
            )
            markers.append(marker)
        return markers

    def take_new_since(self, index: int) -> Tuple[List[Dict[str, Any]], int]:
        """取出自 ``index`` 以来新增的引用（供 SSE ``citations`` 事件增量推送）。

        Args:
            index: 上一次已推送的游标（已推送条数）。

        Returns:
            ``(新增引用列表, 新的游标)``。新增列表为空时游标不变。
        """
        new = self._citations[index:]
        return [dict(c) for c in new], index + len(new)

    def snapshot(self) -> List[Dict[str, Any]]:
        """返回当前已登记的全部引用（深拷贝，避免外部修改内部状态）。"""
        return [dict(c) for c in self._citations]

    def __len__(self) -> int:
        return len(self._citations)
