"""向量删除回归测试（A2 / D7）

**缺陷回顾**：``delete_document`` 曾把 ``chunk.vector_id``（裸字符串）直接传给
``qdrant.delete(points_selector=...)``。qdrant-client 只接受 ``PointIdsList`` /
``Filter`` / ``list`` 等类型，传入字符串会抛
``ValueError: Unsupported points selector type: <class 'str'>``；
该异常又被 ``except Exception: pass`` 吞掉，于是**删除文档后向量永远残留**，
已下架的内容仍会被检索命中，而日志里没有任何痕迹。

本文件分两层防护：

* ``TestDeleteDocumentSelector`` —— 不依赖 Qdrant，断言 Service 传给客户端的
  选择器类型正确、清理覆盖**两个集合**（灰度指针所指的新集合 + 旧集合）、
  且失败时会留下日志（异常不再被静默吞掉）；
* ``TestQdrantDeleteMechanics`` —— 对真实 Qdrant 的集成验证，证明旧写法确实失败、
  新写法确实生效（服务不可达时自动跳过）。
"""

import logging
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from qdrant_client.models import PointIdsList

from app.services.knowledge import KnowledgeBaseService

TENANT = "tenant-1"
KB_ID = "kb-1"
DOC_ID = "doc-1"
#: 引入灰度 / 回滚指针后，重建过的知识库会有第二个集合
V2_COLLECTION = f"kb_{KB_ID}_v2"


def _qdrant_stub(collection_names, *, delete_error=None):
    """构造一个「知道有哪些集合」的 Qdrant 替身

    必须显式给出集合清单：清理路径会先做**存活性判定**再删除（不带缓存的
    ``collection_exists``），对不存在的集合直接跳过。若替身不实现
    ``get_collections``，存活性判定会失败并返回「不存在」，于是删除被静默跳过——
    测试会以为「没调用 delete」是缺陷，实际是替身不真实。
    """
    client = MagicMock()
    client.get_collections.return_value.collections = [
        SimpleNamespace(name=name) for name in collection_names
    ]
    if delete_error is not None:
        client.delete.side_effect = delete_error
    return client


class _StubRepo:
    """最小 Repository 替身：只提供被测方法所需的行为，并记录调用顺序"""

    def __init__(self, obj=None, chunks=None, events=None):
        self._obj = obj
        self._chunks = chunks or []
        self._events = events if events is not None else []

    def get_by_id(self, _resource_id):
        return self._obj

    def get_by_id_including_deleted(self, _resource_id):
        """删除文档时用于定位**可能已软删**的知识库（P2-D）"""
        return self._obj

    def update(self, instance, **kwargs):
        for key, value in kwargs.items():
            setattr(instance, key, value)
        return instance

    def list_by_doc_id(self, _doc_id):
        self._events.append("list_by_doc_id")
        return self._chunks

    def delete_by_doc_id(self, _doc_id):
        """物理删除分块（分块表已取消软删列，见 app/models/knowledge_chunk.py）"""
        self._events.append("delete_by_doc_id")
        return len(self._chunks)


def _service_with_stubs(chunks, *, active_collection=None):
    events: list = []
    kb = SimpleNamespace(
        id=KB_ID,
        tenant_id=TENANT,
        name="kb",
        document_count=1,
        chunk_count=len(chunks),
        embedding_model="BAAI/bge-base-zh-v1.5",
        # 存活的知识库：delete_document 会据此决定是否维护计数（P2-D）
        deleted_at=None,
        # 灰度 / 回滚指针：None 表示未重建，行为与引入该列之前一致
        active_collection=active_collection,
    )
    doc = SimpleNamespace(
        id=DOC_ID,
        kb_id=KB_ID,
        tenant_id=TENANT,
        chunk_count=len(chunks),
        deleted_at=None,
    )

    service = KnowledgeBaseService(db=MagicMock(), tenant_id=TENANT)
    service.kb_repo = _StubRepo(kb)
    service.doc_repo = _StubRepo(doc)
    service.chunk_repo = _StubRepo(chunks=chunks, events=events)
    return service, doc, events


class TestDeleteDocumentSelector:
    def test_passes_point_ids_list_not_bare_string(self, monkeypatch):
        """向量选择器必须是 PointIdsList，且一次批量提交（而非逐条删除）"""
        chunks = [
            SimpleNamespace(vector_id="11111111-1111-1111-1111-111111111111"),
            SimpleNamespace(vector_id="22222222-2222-2222-2222-222222222222"),
        ]
        service, _, _ = _service_with_stubs(chunks)

        captured = {}
        fake_qdrant = _qdrant_stub([f"kb_{KB_ID}"])
        fake_qdrant.delete.side_effect = lambda **kwargs: captured.update(kwargs)
        monkeypatch.setattr("app.services.knowledge.get_qdrant_client", lambda: fake_qdrant)

        service.delete_document(DOC_ID)

        assert fake_qdrant.delete.call_count == 1, "应合并为一次批量删除"
        selector = captured["points_selector"]
        assert isinstance(selector, PointIdsList)
        assert selector.points == [chunk.vector_id for chunk in chunks]
        assert not isinstance(selector, str)
        assert captured["collection_name"] == f"kb_{KB_ID}"

    def test_purges_both_collections_when_pointer_set(self, monkeypatch):
        """已重建的知识库有两个集合：指针所指的新集合 **与** 旧集合都要清理

        若只清当前生效集合，另一集合里的向量会成为孤儿——内容不会进入回答
        （回表查不到分块行），但会持续占用存储并让「集合点数 vs 分块行数」的对账失真。
        """
        chunks = [SimpleNamespace(vector_id="vec-1")]
        service, _, _ = _service_with_stubs(chunks, active_collection=V2_COLLECTION)

        fake_qdrant = _qdrant_stub([f"kb_{KB_ID}", V2_COLLECTION])
        monkeypatch.setattr("app.services.knowledge.get_qdrant_client", lambda: fake_qdrant)

        service.delete_document(DOC_ID)

        purged = {call.kwargs["collection_name"] for call in fake_qdrant.delete.call_args_list}
        assert purged == {f"kb_{KB_ID}", V2_COLLECTION}

    def test_skips_collection_that_does_not_exist(self, monkeypatch):
        """不存在的集合必须跳过，不产生注定失败且会误报的删除请求"""
        service, _, _ = _service_with_stubs(
            [SimpleNamespace(vector_id="vec-1")], active_collection=V2_COLLECTION
        )
        # 只有新集合存在（旧集合已在回收窗口后被删除）
        fake_qdrant = _qdrant_stub([V2_COLLECTION])
        monkeypatch.setattr("app.services.knowledge.get_qdrant_client", lambda: fake_qdrant)

        service.delete_document(DOC_ID)

        assert fake_qdrant.delete.call_count == 1
        assert fake_qdrant.delete.call_args.kwargs["collection_name"] == V2_COLLECTION

    def test_skips_qdrant_when_no_vector_ids(self, monkeypatch):
        """无向量 ID 时不应发起空的删除请求"""
        service, _, _ = _service_with_stubs([SimpleNamespace(vector_id=None)])
        fake_qdrant = _qdrant_stub([f"kb_{KB_ID}"])
        monkeypatch.setattr("app.services.knowledge.get_qdrant_client", lambda: fake_qdrant)

        service.delete_document(DOC_ID)
        fake_qdrant.delete.assert_not_called()

    def test_chunks_deleted_after_vector_cleanup(self, monkeypatch):
        """删除文档必须级联删除分块，且顺序在取分块之后

        顺序反了会导致 ``list_by_doc_id`` 查不到记录、向量清理被静默跳过——
        A2 与 D9 叠加后的表现正是「文档看似已删，内容仍被检索命中」。

        分块侧是**物理删除**（分块表已无软删列）：软删行会长期占用 ``vector_id``
        唯一索引，让重建时新旧两代算出同一个 id 并撞唯一约束。
        """
        chunks = [SimpleNamespace(vector_id="vec-1"), SimpleNamespace(vector_id="vec-2")]
        service, _, events = _service_with_stubs(chunks)
        monkeypatch.setattr(
            "app.services.knowledge.get_qdrant_client",
            lambda: _qdrant_stub([f"kb_{KB_ID}"]),
        )

        service.delete_document(DOC_ID)

        assert events == ["list_by_doc_id", "delete_by_doc_id"], (
            "必须先取分块清理向量，再级联删除分块"
        )

    def test_failure_is_logged_not_swallowed(self, monkeypatch, caplog):
        """删除失败必须留痕：异常被静默吞掉是 A2 长期未被发现的直接原因"""
        service, doc, _ = _service_with_stubs([SimpleNamespace(vector_id="vec-1")])
        fake_qdrant = _qdrant_stub(
            [f"kb_{KB_ID}"], delete_error=RuntimeError("qdrant down")
        )
        monkeypatch.setattr("app.services.knowledge.get_qdrant_client", lambda: fake_qdrant)

        with caplog.at_level(logging.WARNING, logger="app.services.knowledge"):
            service.delete_document(DOC_ID)  # 不应抛出

        assert any("Failed to delete" in record.message for record in caplog.records)
        assert doc.deleted_at is not None, "向量清理失败不应阻断软删除主流程"


def _connect_or_skip():
    """Qdrant 可达性探测：不可达时跳过集成用例而不是让整套测试报错"""
    from app.core.vector_db import get_qdrant_client

    try:
        client = get_qdrant_client()
        client.get_collections()
        return client
    except Exception as exc:  # noqa: BLE001 - 集成用例的统一跳过出口
        pytest.skip(f"Qdrant 不可达，跳过向量删除集成验证：{exc}")


@pytest.mark.integration
class TestQdrantDeleteMechanics:
    """在真实 Qdrant 上验证「旧写法失败 / 新写法生效」，隔离于生产 collection"""

    @pytest.fixture
    def temp_collection(self):
        from qdrant_client.models import Distance, VectorParams

        client = _connect_or_skip()
        name = f"kb_pytest_{uuid.uuid4()}"
        client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(size=8, distance=Distance.COSINE),
        )
        try:
            yield client, name
        finally:
            client.delete_collection(collection_name=name)

    def test_bare_string_selector_is_rejected(self, temp_collection):
        """旧写法（裸字符串）必须失败——这是 A2 的根因证据"""
        client, name = temp_collection
        with pytest.raises(ValueError, match="Unsupported points selector"):
            client.delete(collection_name=name, points_selector="not-a-valid-selector")

    def test_point_ids_list_removes_points(self, temp_collection):
        """新写法（PointIdsList）必须真正删净向量"""
        from qdrant_client.models import PointStruct

        client, name = temp_collection
        point_ids = [str(uuid.uuid4()) for _ in range(3)]
        client.upsert(
            collection_name=name,
            points=[
                PointStruct(id=point_id, vector=[0.1] * 8, payload={"probe": True})
                for point_id in point_ids
            ],
        )
        assert client.count(name, exact=True).count == 3

        client.delete(collection_name=name, points_selector=PointIdsList(points=point_ids))
        assert client.count(name, exact=True).count == 0
