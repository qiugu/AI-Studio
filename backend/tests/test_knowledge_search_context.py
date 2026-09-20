"""``KnowledgeBaseService.search`` 的上下文装配契约（P4）

覆盖的是**用户可见的语义**，而不是实现细节：

* 检索结果新增的 ``llm_content`` / ``context_header`` / ``context_expanded`` 三键
  **恒显式出现**，且 ``content`` 在装配后仍与入库文本逐字符相同——``content`` 同时
  是去重键、前端展示文本与既有调用方取值处，被注入即成为脏数据；
* 上下文头把「文件名 / 小节 / 页码区间」按需前置，并**如实表达粗化**（
  ``heading_path_mixed`` 为真时输出「等小节」）；
* 邻块窗口覆盖 ``chunk_index ± N``，缺块时不补空、不报错；
* 邻块按 **(文档, 命中块自身的代次)** 归组查询，每组合并一次。代次必须取自命中块，
  不能取配置里的当前代——回滚到旧集合后按当前代查会取到**新代的同下标块**，把两代
  内容拼进同一次回答，且不报任何错。

全部依赖以替身注入，不连 Qdrant、不连 MySQL、不加载真实模型。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest

from app.core.vector_db import RetrievedPoint
from app.services.knowledge import KnowledgeBaseService
from tests._chunk_doubles import chunk_double
from tests._repo_doubles import chunk_repo_double

KB_ID = "11111111-2222-3333-4444-555555555555"
TENANT = "tenant-1"
DOC_ID = "doc-1"
EPOCH = "448-64-p1"


class Harness:
    """只依赖替身的服务实例 + 邻块查询记录

    邻块查询由 :func:`tests._repo_doubles.chunk_repo_double` 提供：它复刻了真实仓储
    的「文档 + 代次 + 下标集合」三重过滤。**刻意复刻代次过滤**——若装配层传的是配置
    里的当前代而非命中块自身代次，这个替身就会返回**另一种代**的同下标行，正是本文件
    要测出的那个静默故障。
    """

    def __init__(self, chunks: List[SimpleNamespace]):
        self.chunks = chunks
        self.by_vector = {chunk.vector_id: chunk for chunk in chunks}
        self.neighbor_calls: List[Dict[str, Any]] = []
        self.neighbor_rows: List[SimpleNamespace] | None = None
        self.service: KnowledgeBaseService = None  # type: ignore[assignment]


def chunk(**overrides) -> SimpleNamespace:
    """分块替身：默认落在同一文档、同一代次、文件名 ``手册.pdf``

    ``vector_id`` 默认由 ``chunk_index`` 派生，故同一用例内出现**重复下标**时
    （跨文档、跨代次的同位置块）必须显式给 ``vector_id``，否则两条行会共用同一个
    键而在替身里互相覆盖——表现为「用例明明构造了两行却只查到一行」。
    """
    defaults: Dict[str, Any] = {
        "doc_id": DOC_ID,
        "chunk_epoch": EPOCH,
        "document": SimpleNamespace(file_name="手册.pdf"),
    }
    defaults.update(overrides)
    index = defaults.get("chunk_index", 0)
    vector_id = defaults.pop("vector_id", f"v{index}")
    return chunk_double(id=f"chunk-{vector_id}", vector_id=vector_id, **defaults)


def make_harness(chunks, monkeypatch, neighbor_rows=None) -> Harness:
    """构造替身服务；召回归属顺序 = ``chunks`` 的给定顺序（分数随之递减）

    Args:
        neighbor_rows: 传空列表可模拟「邻块行全部不可见」。必须在构造替身**时**
            传入——替身闭包在构造时绑定实参，事后改 ``harness.neighbor_rows``
            不会生效。
    """
    harness = Harness(chunks)
    harness.neighbor_rows = neighbor_rows
    dense_order = [chunk_.vector_id for chunk_ in chunks]

    service = KnowledgeBaseService(db=MagicMock(), tenant_id=TENANT)
    service.get_knowledge_base = lambda _kb_id: SimpleNamespace(
        id=KB_ID, tenant_id=TENANT, embedding_model="fake/model", active_collection=None
    )
    service.chunk_repo = chunk_repo_double(
        chunks,
        calls=harness.neighbor_calls,
        neighbor_rows=neighbor_rows,
    )

    monkeypatch.setattr(
        "app.services.knowledge.get_embedding_client",
        lambda **_kwargs: SimpleNamespace(
            embed=lambda texts: [[0.1, 0.2, 0.3] for _ in texts]
        ),
    )
    monkeypatch.setattr(
        "app.services.knowledge.search_points",
        lambda **kwargs: [
            RetrievedPoint(id=vector_id, score=0.9 - index * 0.05)
            for index, vector_id in enumerate(dense_order[: kwargs["limit"]])
        ],
    )

    harness.service = service
    return harness


@pytest.fixture
def flags(monkeypatch):
    """装配开关的独立控制句柄（用例按需覆写）"""
    from app.core import config as config_module

    settings = {
        "retrieval_context_header_enabled": True,
        "retrieval_neighbor_expansion": 1,
        "retrieval_dedup_enabled": True,
        "retrieval_fetch_multiplier": 2,
        "retrieval_score_threshold": 0.0,
        "reranker_enabled": False,
        "chunk_overlap": 64,
    }
    for key, value in settings.items():
        monkeypatch.setattr(config_module.config, key, value, raising=False)
    return config_module.config


class TestContentImmutability:
    def test_content_keeps_raw_text(self, monkeypatch, flags):
        """``content`` 不得被注入污染；装配结果只写 ``llm_content``"""
        harness = make_harness(
            [
                chunk(chunk_index=0, content="块零", source_page=1, source_page_end=1),
                chunk(chunk_index=1, content="块一", source_page=2, source_page_end=2),
            ],
            monkeypatch,
        )

        results = harness.service.search(KB_ID, "查询", top_k=1)

        assert results[0]["content"] == "块零"
        assert "块零" in results[0]["llm_content"]
        assert results[0]["llm_content"] != results[0]["content"]

    def test_assembly_does_no_lookup_when_both_flags_off(self, monkeypatch, flags):
        """两个开关全关时不做任何回表，且三键仍显式出现（契约不随配置漂移）"""
        flags.retrieval_context_header_enabled = False
        flags.retrieval_neighbor_expansion = 0
        harness = make_harness(
            [
                chunk(chunk_index=0, content="块零", source_page=1, source_page_end=1),
                chunk(chunk_index=1, content="块一", source_page=2, source_page_end=2),
            ],
            monkeypatch,
        )

        results = harness.service.search(KB_ID, "查询", top_k=2)

        assert harness.neighbor_calls == []
        for item in results:
            assert item["llm_content"] == item["content"]
            assert item["context_header"] is None
            assert item["context_expanded"] is False


class TestContextHeader:
    def test_pdf_header_shows_page_range(self, monkeypatch, flags):
        """PDF 有页码无标题路径：头部只带文件名与页码范围"""
        harness = make_harness(
            [chunk(chunk_index=0, content="正文", source_page=37, source_page_end=38)],
            monkeypatch,
        )

        results = harness.service.search(KB_ID, "查询", top_k=1)

        assert results[0]["context_header"] == "[《手册.pdf》 | p.37\u201338]"
        assert results[0]["llm_content"].startswith("[《手册.pdf》 | p.37\u201338]\n\n")

    def test_mixed_heading_is_declared(self, monkeypatch, flags):
        """粗化路径必须输出「等小节」，否则引用会断言块出自一个它没有的章节"""
        harness = make_harness(
            [
                chunk(
                    chunk_index=0,
                    content="正文",
                    heading_path="第二章 > 学习路径",
                    heading_path_mixed=True,
                )
            ],
            monkeypatch,
        )

        results = harness.service.search(KB_ID, "查询", top_k=1)

        assert results[0]["context_header"] == "[《手册.pdf》 | § 第二章 > 学习路径 等小节]"

    def test_no_source_means_no_header(self, monkeypatch, flags):
        """无任何出处信息时不硬造头部；``llm_content`` 仍等于正文"""
        harness = make_harness(
            [chunk(chunk_index=0, content="正文", document=None)],
            monkeypatch,
        )

        results = harness.service.search(KB_ID, "查询", top_k=1)

        assert results[0]["context_header"] is None
        assert results[0]["llm_content"] == results[0]["content"]


class TestNeighborWindow:
    def test_window_covers_prev_self_next(self, monkeypatch, flags):
        """中间块：窗口含前后各一块，按 chunk_index 升序拼接"""
        harness = make_harness(
            [
                chunk(chunk_index=1, content="第二段"),
                chunk(chunk_index=0, content="第一段"),
                chunk(chunk_index=2, content="第三段"),
            ],
            monkeypatch,
        )

        results = harness.service.search(KB_ID, "查询", top_k=1)

        body = results[0]["llm_content"].split("\n\n", 1)[1]
        assert body == "第一段\n\n第二段\n\n第三段"
        assert results[0]["context_expanded"] is True

    def test_first_chunk_has_no_negative_neighbor(self, monkeypatch, flags):
        """首块无前邻：不得请求下标 -1，窗口只含自身与后一块"""
        harness = make_harness(
            [
                chunk(chunk_index=0, content="第一段"),
                chunk(chunk_index=1, content="第二段"),
            ],
            monkeypatch,
        )

        results = harness.service.search(KB_ID, "查询", top_k=1)

        assert harness.neighbor_calls[0]["chunk_indexes"] == [0, 1]
        assert results[0]["llm_content"].endswith("第一段\n\n第二段")

    def test_missing_trailing_neighbor_is_not_padded(self, monkeypatch, flags):
        """末块：请求了下标 2 但不存在，窗口只含实际存在的块，不补空段"""
        harness = make_harness(
            [
                chunk(chunk_index=1, content="第二段"),
                chunk(chunk_index=0, content="第一段"),
            ],
            monkeypatch,
        )

        results = harness.service.search(KB_ID, "查询", top_k=1)

        assert harness.neighbor_calls[0]["chunk_indexes"] == [0, 1, 2]
        body = results[0]["llm_content"].split("\n\n", 1)[1]
        assert body == "第一段\n\n第二段"
        assert "\n\n\n" not in body

    def test_single_chunk_document_is_not_expanded(self, monkeypatch, flags):
        """只有一块的文档：无邻块可拼，``context_expanded`` 为假而不报错"""
        harness = make_harness([chunk(chunk_index=0, content="唯一段")], monkeypatch)

        results = harness.service.search(KB_ID, "查询", top_k=1)

        assert results[0]["context_expanded"] is False
        assert results[0]["llm_content"].endswith("唯一段")

    def test_no_visible_neighbors_falls_back_to_own_content(self, monkeypatch, flags):
        """邻块行全部不可见（已软删 / 已清理）时退回块原文，不产生空窗口"""
        harness = make_harness(
            [chunk(chunk_index=0, content="唯一可见段")],
            monkeypatch,
            neighbor_rows=[],
        )

        results = harness.service.search(KB_ID, "查询", top_k=1)

        assert results[0]["context_expanded"] is False
        assert "唯一可见段" in results[0]["llm_content"]

    def test_neighbors_come_from_hit_epoch_not_configured_epoch(self, monkeypatch, flags):
        """邻块必须取自**命中块自身的代次**

        构造：命中块属旧代 ``448-64``（模拟回滚到旧集合后），另有新代
        ``448-64-p1`` 的同下标行。若实现取配置里的当前代（新代），窗口会拼进新代
        内容——两代内容混进同一次回答，且没有任何报错。
        """
        harness = make_harness(
            [
                chunk(chunk_index=1, content="旧代第二段", chunk_epoch="448-64",
                      vector_id="v-old-1"),
                chunk(chunk_index=0, content="旧代第一段", chunk_epoch="448-64",
                      vector_id="v-old-0"),
                chunk(chunk_index=0, content="新代第一段", chunk_epoch=EPOCH,
                      vector_id="v-new-0"),
                chunk(chunk_index=1, content="新代第二段", chunk_epoch=EPOCH,
                      vector_id="v-new-1"),
            ],
            monkeypatch,
        )

        results = harness.service.search(KB_ID, "查询", top_k=1)

        assert harness.neighbor_calls[0]["chunk_epoch"] == "448-64"
        window = results[0]["llm_content"]
        assert "旧代第一段" in window and "旧代第二段" in window
        assert "新代" not in window

    def test_neighbor_query_is_merged_per_document(self, monkeypatch, flags):
        """同文档多个命中合并为一次邻块查询（按 (doc_id, epoch) 归组）"""
        harness = make_harness(
            [
                chunk(chunk_index=1, content="B"),
                chunk(chunk_index=3, content="D"),
                chunk(chunk_index=0, content="A"),
                chunk(chunk_index=2, content="C"),
                chunk(chunk_index=4, content="E"),
            ],
            monkeypatch,
        )

        harness.service.search(KB_ID, "查询", top_k=2)

        assert len(harness.neighbor_calls) == 1
        assert harness.neighbor_calls[0]["chunk_indexes"] == [0, 1, 2, 3, 4]

    def test_two_documents_are_queried_separately(self, monkeypatch, flags):
        """不同文档必须分开查询，否则会拿到别的文档的同下标内容"""
        harness = make_harness(
            [
                chunk(chunk_index=0, content="甲-1"),
                chunk(chunk_index=0, content="乙-1", doc_id="doc-2", vector_id="v-doc2"),
            ],
            monkeypatch,
        )

        harness.service.search(KB_ID, "查询", top_k=2)

        assert [call["doc_id"] for call in harness.neighbor_calls] == [
            DOC_ID,
            "doc-2",
        ]

    def test_expansion_applies_only_to_returned_top_k(self, monkeypatch, flags):
        """扩展只作用于最终返回的 top_k，宽召回候选不做无用回表"""
        harness = make_harness(
            [
                chunk(chunk_index=0, content="A"),
                chunk(chunk_index=1, content="B"),
                chunk(chunk_index=2, content="C"),
                chunk(chunk_index=3, content="D"),
            ],
            monkeypatch,
        )

        harness.service.search(KB_ID, "查询", top_k=1)

        assert len(harness.neighbor_calls) == 1
        assert harness.neighbor_calls[0]["chunk_indexes"] == [0, 1]

    def test_radius_can_be_widened(self, monkeypatch, flags):
        """半径可配置：取 2 时窗口覆盖前后各两块"""
        flags.retrieval_neighbor_expansion = 2
        harness = make_harness(
            [
                chunk(chunk_index=2, content="第三段"),
                chunk(chunk_index=1, content="第二段"),
                chunk(chunk_index=0, content="第一段"),
            ],
            monkeypatch,
        )

        results = harness.service.search(KB_ID, "查询", top_k=1)

        assert harness.neighbor_calls[0]["chunk_indexes"] == [0, 1, 2, 3, 4]
        body = results[0]["llm_content"].split("\n\n", 1)[1]
        assert body == "第一段\n\n第二段\n\n第三段"

    def test_chunk_overlap_is_trimmed_in_window(self, monkeypatch, flags):
        """窗口内相邻块的重叠部分必须裁掉，避免同一句在上下文里出现两次"""
        overlap = "ABCDEFGHIJKLMNOP"
        harness = make_harness(
            [
                chunk(chunk_index=0, content=f"前文{overlap}"),
                chunk(chunk_index=1, content=f"{overlap}后文"),
            ],
            monkeypatch,
        )

        results = harness.service.search(KB_ID, "查询", top_k=1)

        body = results[0]["llm_content"].split("\n\n", 1)[1]
        assert body == f"前文{overlap}\n\n后文"
        assert body.count(overlap) == 1


class TestResponseMarker:
    """检索响应内编号（见 plan §Phase 1 两套 marker 作用域之「响应内编号」）"""

    def test_marker_equals_index_plus_one(self, monkeypatch, flags):
        harness = make_harness(
            [
                chunk(chunk_index=0, content="A"),
                chunk(chunk_index=1, content="B"),
                chunk(chunk_index=2, content="C"),
            ],
            monkeypatch,
        )
        results = harness.service.search(KB_ID, "查询", top_k=3)
        assert [r["marker"] for r in results] == [1, 2, 3]

    def test_marker_continuous_when_top_k_changes(self, monkeypatch, flags):
        harness = make_harness(
            [chunk(chunk_index=i, content=f"C{i}") for i in range(5)],
            monkeypatch,
        )
        results = harness.service.search(KB_ID, "查询", top_k=5)
        assert [r["marker"] for r in results] == [1, 2, 3, 4, 5]

    def test_empty_results_have_no_marker_entries(self, monkeypatch, flags):
        harness = make_harness([], monkeypatch)
        results = harness.service.search(KB_ID, "查询", top_k=3)
        # 无结果返回空列表而非 [None]，前端按长度判断而非按内容
        assert results == []
