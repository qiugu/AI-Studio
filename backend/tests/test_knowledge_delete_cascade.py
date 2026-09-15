"""知识库删除的级联契约（P2-C）与「库删后文档仍可清理」（P2-D）

缺陷回顾：

* **P2-C**：``delete_knowledge_base`` 曾只把知识库行标记软删，不触碰文档、分块与
  Qdrant 集合。表现为「接口返回 200，但文档仍可查、分块仍在、向量永久残留」。
* **P2-D**：``delete_document`` 曾先校验知识库存在，而校验会过滤软删知识库。
  于是知识库一经删除，其残留文档就**再也无法通过任何接口清理**——P2-C 的部分
  成功被永久固化，只能人工介入数据库与向量库。

两者合起来构成「删除不彻底 + 无法补救」的组合缺陷，因此放在同一文件覆盖。

全部依赖以替身注入：不连数据库、不连 Qdrant。
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services.knowledge import KnowledgeBaseService

TENANT = "tenant-1"
KB_ID = "kb-1"


class _StubChunkRepo:
    def __init__(self, chunks_by_doc, events):
        self._by_doc = chunks_by_doc
        self._events = events

    def list_by_doc_id(self, doc_id):
        # 记录顺序：必须「先取分块、再删除」，否则向量清理会静默跳过
        self._events.append(f"list_chunks:{doc_id}")
        return list(self._by_doc.get(doc_id, []))

    def delete_by_doc_id(self, doc_id):
        """物理删除分块（分块表已取消软删列）"""
        self._events.append(f"delete_chunks:{doc_id}")
        return len(self._by_doc.get(doc_id, []))


class _StubDocRepo:
    def __init__(self, docs):
        self._docs = docs

    def list_all_by_kb(self, _kb_id):
        return list(self._docs)

    def get_by_id(self, doc_id):
        return next(
            (d for d in self._docs if d.id == doc_id and d.deleted_at is None), None
        )

    def update(self, instance, **kwargs):
        for key, value in kwargs.items():
            setattr(instance, key, value)
        return instance


class _StubKbRepo:
    def __init__(self, kb):
        self._kb = kb
        self.updates: list[dict] = []

    def get_by_id(self, _kb_id):
        """对外读取：软删后不可见（与 BaseRepository.get_by_id 语义一致）"""
        if self._kb is None or self._kb.deleted_at is not None:
            return None
        return self._kb

    def get_by_id_including_deleted(self, _kb_id):
        """回收路径用：不看软删标记"""
        return self._kb

    def update(self, instance, **kwargs):
        self.updates.append(dict(kwargs))
        for key, value in kwargs.items():
            setattr(instance, key, value)
        return instance


def _qdrant_stub(collection_names):
    """知道「有哪些集合」的 Qdrant 替身

    清理路径会先做存活性判定（不带缓存的 ``collection_exists``），再对存在的集合
    发起删除。替身若不实现 ``get_collections``，判定会失败并返回「不存在」，
    删除被静默跳过——测试会误判成缺陷。
    """
    client = MagicMock()
    client.get_collections.return_value.collections = [
        SimpleNamespace(name=name) for name in collection_names
    ]
    return client


def _make_service(*, kb_deleted: bool, doc_count: int = 2, chunks_per_doc: int = 3):
    docs = [
        SimpleNamespace(
            id=f"doc-{i}",
            kb_id=KB_ID,
            tenant_id=TENANT,
            chunk_count=chunks_per_doc,
            deleted_at=None,
        )
        for i in range(doc_count)
    ]
    chunks_by_doc = {
        doc.id: [SimpleNamespace(vector_id=f"vec-{doc.id}-{j}") for j in range(chunks_per_doc)]
        for doc in docs
    }
    kb = SimpleNamespace(
        id=KB_ID,
        tenant_id=TENANT,
        name="kb",
        document_count=doc_count,
        chunk_count=doc_count * chunks_per_doc,
        embedding_model="fake/model",
        deleted_at="2026-09-11 00:00:00" if kb_deleted else None,
        # 未重建的知识库：指针为空，行为与引入该列之前一致
        active_collection=None,
    )

    events: list[str] = []
    service = KnowledgeBaseService(db=MagicMock(), tenant_id=TENANT)
    service.kb_repo = _StubKbRepo(kb)
    service.doc_repo = _StubDocRepo(docs)
    service.chunk_repo = _StubChunkRepo(chunks_by_doc, events)
    return service, kb, docs, events


class TestDeleteKnowledgeBaseCascade:
    def test_documents_and_chunks_are_cascaded(self, monkeypatch):
        """删库必须级联软删其全部文档与分块（P2-C）"""
        service, kb, docs, events = _make_service(kb_deleted=False)
        monkeypatch.setattr(
            "app.services.knowledge.delete_collection", lambda _kb_id, **_kw: True
        )

        service.delete_knowledge_base(KB_ID)

        assert kb.deleted_at is not None
        for doc in docs:
            assert doc.deleted_at is not None, "文档未被级联软删"
        assert sorted(events) == sorted(
            [
                "list_chunks:doc-0", "delete_chunks:doc-0",
                "list_chunks:doc-1", "delete_chunks:doc-1",
            ]
        ), "必须先取分块、再软删分块"

    def test_counts_are_reset(self, monkeypatch):
        """计数归零，避免删库后残留「还有 N 个文档」的假象"""
        service, kb, _, _ = _make_service(kb_deleted=False)
        monkeypatch.setattr(
            "app.services.knowledge.delete_collection", lambda _kb_id, **_kw: True
        )

        service.delete_knowledge_base(KB_ID)

        assert kb.document_count == 0
        assert kb.chunk_count == 0

    def test_qdrant_collection_is_dropped(self, monkeypatch):
        """向量回收采用删除整个集合：逐点删除会漏掉存量脏数据（P2-C）"""
        service, _, _, _ = _make_service(kb_deleted=False)
        captured: list[str] = []
        monkeypatch.setattr(
            "app.services.knowledge.delete_collection",
            lambda kb_id, **_kw: captured.append(kb_id) or True,
        )
        fake_qdrant = _qdrant_stub([f"kb_{KB_ID}"])
        monkeypatch.setattr("app.services.knowledge.get_qdrant_client", lambda: fake_qdrant)

        service.delete_knowledge_base(KB_ID)

        assert captured == [KB_ID]
        # 集合整体删除后不应再逐点删除
        fake_qdrant.delete.assert_not_called()

    def test_collection_drop_failure_is_logged_not_raised(self, monkeypatch, caplog):
        """集合删除失败只影响存储回收，不应让已成功的业务操作失败"""
        service, kb, _, _ = _make_service(kb_deleted=False)

        def _boom(_kb_id, **_kw):
            raise RuntimeError("qdrant down")

        monkeypatch.setattr("app.services.knowledge.delete_collection", _boom)

        with caplog.at_level(logging.WARNING, logger="app.services.knowledge"):
            service.delete_knowledge_base(KB_ID)  # 不应抛出

        assert kb.deleted_at is not None
        assert any("Failed to drop Qdrant collection" in r.message for r in caplog.records)


class TestDeleteKnowledgeBaseDropsBothCollections:
    def test_active_collection_pointer_is_passed_through(self, monkeypatch):
        """删库时必须把灰度指针一起传给集合回收

        重建过的知识库有「新集合（指针所指）」与「旧集合」两个；知识库已删便不存在
        可回滚的对象，两个都必须回收。若只传 kb_id，新集合会永久残留——
        而它往往是存储占用更大的那个。
        """
        service, kb, _, _ = _make_service(kb_deleted=False)
        kb.active_collection = f"kb_{KB_ID}_v2"
        captured: list[dict] = []
        monkeypatch.setattr(
            "app.services.knowledge.delete_collection",
            lambda kb_id, **kw: captured.append({"kb_id": kb_id, **kw}) or True,
        )
        monkeypatch.setattr(
            "app.services.knowledge.get_qdrant_client", lambda: _qdrant_stub([f"kb_{KB_ID}"])
        )

        service.delete_knowledge_base(KB_ID)

        assert captured == [{"kb_id": KB_ID, "active": f"kb_{KB_ID}_v2"}]


class TestDeleteDocumentAfterKnowledgeBaseRemoved:
    def test_document_can_still_be_purged(self, monkeypatch):
        """知识库已软删时，其文档仍必须能被清理（P2-D）

        这是 P2-C 的补救路径：若此处失败，残留文档与向量将永久无法回收。
        """
        service, _, docs, events = _make_service(kb_deleted=True)
        fake_qdrant = _qdrant_stub([f"kb_{KB_ID}"])
        monkeypatch.setattr("app.services.knowledge.get_qdrant_client", lambda: fake_qdrant)

        service.delete_document("doc-0")  # 不应抛 NotFoundException

        assert docs[0].deleted_at is not None
        fake_qdrant.delete.assert_called_once()
        assert events == ["list_chunks:doc-0", "delete_chunks:doc-0"]

    def test_counts_are_not_touched_when_kb_is_deleted(self, monkeypatch):
        """知识库已删时其计数已在删库时归零，再减会掩盖真实回收进度"""
        service, kb, _, _ = _make_service(kb_deleted=True)
        monkeypatch.setattr(
            "app.services.knowledge.get_qdrant_client", lambda: _qdrant_stub([f"kb_{KB_ID}"])
        )

        service.delete_document("doc-0")

        assert service.kb_repo.updates == []

    def test_counts_are_decremented_when_kb_is_alive(self, monkeypatch):
        """反向断言：知识库存活时计数必须正常维护，不能被上面的放宽逻辑带偏"""
        service, kb, _, _ = _make_service(kb_deleted=False)
        monkeypatch.setattr(
            "app.services.knowledge.get_qdrant_client", lambda: _qdrant_stub([f"kb_{KB_ID}"])
        )

        service.delete_document("doc-0")

        assert kb.document_count == 1
        assert kb.chunk_count == 3
