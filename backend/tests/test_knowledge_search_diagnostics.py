"""检索诊断契约（P2-E）

缺陷回顾：``search()`` 在 Qdrant 异常时统一 ``return []``，使「后端故障」与
「确无相关内容」在调用侧完全不可区分。本项目在首轮勘察中即因此把「集合不存在」
误读为「库里没有向量」，得出了与事实完全相反的结论——而日志里只有一句
``Qdrant search failed``，没有任何可用于区分的信息。

本文件覆盖三条契约：

1. 故障可归因：集合缺失与后端不可用必须给出不同的 ``reason``；
2. 日志分级：集合缺失是配置/数据故障（``error``），后端不可用是瞬时故障（``warning``）；
3. 契约不变：``search()`` 仍返回 list，且与 ``search_with_diagnostics().results``
   逐条一致——诊断能力的引入不得改变既有调用方看到的结果。
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.core.exceptions import ValidationException
from app.core.vector_db import RetrievedPoint
from app.services.knowledge import (
    DEGRADED_BACKEND_UNAVAILABLE,
    DEGRADED_COLLECTION_NOT_FOUND,
    KnowledgeBaseService,
    SearchOutcome,
)

KB_ID = "kb-1"
TENANT = "tenant-1"


class _QdrantNotFound(Exception):
    """模拟 qdrant-client 在集合不存在时的报错形态"""

    status_code = 404


def _service(chunks_by_vector=None):
    chunks_by_vector = chunks_by_vector or {}
    service = KnowledgeBaseService(db=MagicMock(), tenant_id=TENANT)
    service.get_knowledge_base = lambda _kb_id: SimpleNamespace(
        id=KB_ID, tenant_id=TENANT, embedding_model="fake/model", active_collection=None
    )
    service.chunk_repo = MagicMock()
    service.chunk_repo.list_by_vector_ids = lambda ids: [
        chunks_by_vector[v] for v in ids if v in chunks_by_vector
    ]
    return service


@pytest.fixture(autouse=True)
def _fast_embedding(monkeypatch):
    """避免加载真实模型：诊断逻辑与向量内容无关"""
    monkeypatch.setattr(
        "app.services.knowledge.get_embedding_client",
        lambda **_kwargs: SimpleNamespace(embed=lambda texts: [[0.1, 0.2] for _ in texts]),
    )
    # 默认关闭精排与去重，使被测路径最短；需要时由用例自行覆盖
    monkeypatch.setattr("app.services.knowledge.config.reranker_enabled", False, raising=False)
    monkeypatch.setattr("app.services.knowledge.config.retrieval_dedup_enabled", False, raising=False)


def _patch_search_points(monkeypatch, behaviour):
    monkeypatch.setattr("app.services.knowledge.search_points", behaviour)


class TestNormalPath:
    def test_returns_outcome_without_degradation(self, monkeypatch):
        chunk = SimpleNamespace(
            id="chunk-1",
            vector_id="v1",
            content="内容",
            doc_id="doc-1",
            chunk_index=0,
            source_page=None,
            heading_path=None,
            document=SimpleNamespace(file_name="a.pdf"),
        )
        _patch_search_points(monkeypatch, lambda **_kw: [RetrievedPoint(id="v1", score=0.9)])
        service = _service({"v1": chunk})

        outcome = service.search_with_diagnostics(kb_id=KB_ID, query="问")

        assert isinstance(outcome, SearchOutcome)
        assert outcome.degraded is False
        assert outcome.reason is None
        assert outcome.collection == f"kb_{KB_ID}"
        assert outcome.results[0]["content"] == "内容"

    def test_search_returns_same_list_as_diagnostics(self, monkeypatch):
        """契约不变：search() 的 list 与 search_with_diagnostics().results 一致"""
        chunk = SimpleNamespace(
            id="chunk-1",
            vector_id="v1",
            content="内容",
            doc_id="doc-1",
            chunk_index=0,
            source_page=None,
            heading_path=None,
            document=SimpleNamespace(file_name="a.pdf"),
        )
        _patch_search_points(monkeypatch, lambda **_kw: [RetrievedPoint(id="v1", score=0.9)])
        service = _service({"v1": chunk})

        assert service.search(kb_id=KB_ID, query="问") == service.search_with_diagnostics(
            kb_id=KB_ID, query="问"
        ).results

    def test_empty_query_is_rejected(self, monkeypatch):
        _patch_search_points(monkeypatch, lambda **_kw: [])
        service = _service()
        with pytest.raises(ValidationException):
            service.search_with_diagnostics(kb_id=KB_ID, query="   ")


class TestDegradedPath:
    def test_collection_missing_is_attributed_and_logged_as_error(self, monkeypatch, caplog):
        def _boom(**_kwargs):
            raise _QdrantNotFound("Collection `kb_kb-1` doesn't exist!")

        _patch_search_points(monkeypatch, _boom)
        service = _service()

        with caplog.at_level(logging.DEBUG, logger="app.services.knowledge"):
            outcome = service.search_with_diagnostics(kb_id=KB_ID, query="问")

        assert outcome.degraded is True
        assert outcome.reason == DEGRADED_COLLECTION_NOT_FOUND
        assert outcome.results == []
        assert outcome.collection == f"kb_{KB_ID}"
        assert any(r.levelno == logging.ERROR for r in caplog.records), (
            "集合缺失属配置/数据故障，必须以 error 级别暴露"
        )

    def test_backend_failure_is_attributed_and_logged_as_warning(self, monkeypatch, caplog):
        def _boom(**_kwargs):
            raise RuntimeError("connection reset")

        _patch_search_points(monkeypatch, _boom)
        service = _service()

        with caplog.at_level(logging.DEBUG, logger="app.services.knowledge"):
            outcome = service.search_with_diagnostics(kb_id=KB_ID, query="问")

        assert outcome.reason == DEGRADED_BACKEND_UNAVAILABLE
        assert any(r.levelno == logging.WARNING for r in caplog.records)
        assert not any(r.levelno >= logging.ERROR for r in caplog.records)

    def test_empty_recall_is_not_degraded(self, monkeypatch):
        """召回为空不是故障：两者必须可区分，否则会把「库里没有」误报为故障"""
        _patch_search_points(monkeypatch, lambda **_kw: [])
        service = _service()

        outcome = service.search_with_diagnostics(kb_id=KB_ID, query="问")

        assert outcome.degraded is False
        assert outcome.reason is None
        assert outcome.results == []
