"""向量库混合布局的契约

混合检索要求集合采用「命名稠密 + 命名稀疏」布局。这里守护四件事：

1. **既有路径逐位不变**。``search_points`` 不传 ``using`` 时，发给 Qdrant 的
   参数里**不得出现** ``using`` 键——匿名稠密集合一旦收到 ``using`` 就会报错。
   这是「改造不破坏既有库」的硬约束。
2. **空稀疏向量不当成查询发出去**。Qdrant 拒绝空稀疏向量；而「查询里没有任何
   可匹配词元」（纯标点、纯空白）是完全正常的输入，必须短路返回空列表。
3. **布局探测区分「缺失」与「旧布局」**。二者都必须判为「不可用稀疏」，但语义完全
   不同：缺失时要**创建**目标布局，旧布局只能**回填**。混为一谈会让新建库意外
   沿用旧布局。
4. **不许原地升级**。向已存在的匿名稠密集合请求 ``hybrid=True`` 必须显式失败并
   指向回填脚本，而不是静默返回一个查不到稀疏的集合。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.core import vector_db
from app.core.vector_db import (
    NAMED_DENSE_VECTOR,
    NAMED_SPARSE_VECTOR,
    search_points,
    search_sparse_points,
)


@pytest.fixture(autouse=True)
def _clear_layout_cache():
    """布局探测结果带缓存，用例之间必须隔离"""
    vector_db.reset_layout_cache()
    yield
    vector_db.reset_layout_cache()


def _query_response(ids_and_scores):
    return SimpleNamespace(
        points=[SimpleNamespace(id=i, score=s) for i, s in ids_and_scores]
    )


class TestDenseSearchBackwardCompatibility:
    def test_omits_using_when_not_requested(self):
        """默认调用不得出现 ``using`` 键：匿名稠密集合收到它会直接报错"""
        client = MagicMock()
        client.query_points.return_value = _query_response([("v1", 0.9)])

        result = search_points("kb_x", [0.1, 0.2], limit=5, client=client)

        assert [point.id for point in result] == ["v1"]
        kwargs = client.query_points.call_args.kwargs
        assert "using" not in kwargs, "默认路径不得传 using，否则破坏既有匿名集合检索"

    def test_passes_using_for_hybrid_collections(self):
        client = MagicMock()
        client.query_points.return_value = _query_response([("v1", 0.9)])

        search_points(
            "kb_x", [0.1, 0.2], limit=5, client=client, using=NAMED_DENSE_VECTOR
        )

        assert client.query_points.call_args.kwargs["using"] == NAMED_DENSE_VECTOR

    def test_rejects_non_positive_limit(self):
        with pytest.raises(ValueError):
            search_points("kb_x", [0.1], limit=0, client=MagicMock())


class TestSparseSearch:
    def test_builds_sparse_vector_and_returns_points(self):
        client = MagicMock()
        client.query_points.return_value = _query_response([("v2", 3.5)])

        result = search_sparse_points("kb_x", [10, 20], [1.0, 2.0], limit=5, client=client)

        assert [(point.id, point.score) for point in result] == [("v2", 3.5)]
        query = client.query_points.call_args.kwargs["query"]
        assert list(query.indices) == [10, 20]
        assert list(query.values) == [1.0, 2.0]
        assert client.query_points.call_args.kwargs["using"] == NAMED_SPARSE_VECTOR

    def test_empty_indices_short_circuits(self):
        """空稀疏向量会被 Qdrant 拒绝，且「无词可匹配」本就是正常输入"""
        client = MagicMock()

        assert search_sparse_points("kb_x", [], [], limit=5, client=client) == []
        client.query_points.assert_not_called()

    def test_length_mismatch_rejected(self):
        with pytest.raises(ValueError):
            search_sparse_points("kb_x", [1, 2], [1.0], limit=5, client=MagicMock())

    def test_rejects_non_positive_limit(self):
        with pytest.raises(ValueError):
            search_sparse_points("kb_x", [1], [1.0], limit=-1, client=MagicMock())

    def test_no_score_threshold_is_sent(self):
        """BM25 分数无界，不存在可跨库迁移的绝对阈值——不得传 score_threshold"""
        client = MagicMock()
        client.query_points.return_value = _query_response([])

        search_sparse_points("kb_x", [1], [1.0], limit=5, client=client)

        assert "score_threshold" not in client.query_points.call_args.kwargs


class TestHybridPointVector:
    def test_contains_both_named_vectors(self):
        vector = vector_db.hybrid_point_vector([0.1, 0.2], [7], [1.5])
        assert vector[NAMED_DENSE_VECTOR] == [0.1, 0.2]
        assert list(vector[NAMED_SPARSE_VECTOR].indices) == [7]

    def test_omits_sparse_when_no_tokens(self):
        """文本无可用词元时不得写入空稀疏向量（Qdrant 会拒绝整个 point）"""
        vector = vector_db.hybrid_point_vector([0.1], [], [])
        assert NAMED_SPARSE_VECTOR not in vector
        assert vector[NAMED_DENSE_VECTOR] == [0.1]


class TestCollectionLayout:
    def _client(self, *, sparse_names=None, dense_size=768):
        client = MagicMock()
        client.get_collection.return_value = SimpleNamespace(
            config=SimpleNamespace(
                params=SimpleNamespace(
                    vectors={NAMED_DENSE_VECTOR: SimpleNamespace(size=dense_size)},
                    sparse_vectors={name: object() for name in (sparse_names or [])},
                )
            )
        )
        return client

    def test_detects_hybrid(self):
        client = self._client(sparse_names=[NAMED_SPARSE_VECTOR])
        assert vector_db.collection_layout("kb_x", client=client) == "hybrid"
        assert vector_db.supports_sparse_vectors("kb_x", client=client) is True

    def test_detects_legacy_dense(self):
        client = self._client(sparse_names=[])
        assert vector_db.collection_layout("kb_x", client=client) == "legacy_dense"
        assert vector_db.supports_sparse_vectors("kb_x", client=client) is False

    def test_detects_missing(self):
        client = MagicMock()
        client.get_collection.side_effect = RuntimeError("Not found")
        assert vector_db.collection_layout("kb_x", client=client) == "missing"

    def test_missing_differs_from_legacy(self):
        """二者对入库的含义完全相反（创建 vs 回填），必须可区分"""
        legacy = self._client(sparse_names=[])
        missing = MagicMock()
        missing.get_collection.side_effect = RuntimeError("Not found")
        assert (
            vector_db.collection_layout("kb_a", client=legacy)
            != vector_db.collection_layout("kb_b", client=missing)
        )

    def test_probe_failure_is_not_cached(self):
        """探测失败不得入缓存：否则一次瞬时抖动会固化成 60 秒的持续故障

        缓存「missing」的后果：混合布局的集合被当成旧布局 → 发匿名向量查询 →
        持续 400。必须在下次查询时重新探测以自愈。
        """
        client = MagicMock()
        client.get_collection.side_effect = RuntimeError("transient")

        assert vector_db.collection_layout("kb_x", client=client) == "missing"
        assert vector_db.collection_layout("kb_x", client=client) == "missing"
        assert client.get_collection.call_count == 2, "探测失败的结果被缓存了"

    def test_recovery_after_transient_failure(self):
        """瞬时失败后恢复：下一次探测应拿到真实布局"""
        client = MagicMock()
        client.get_collection.side_effect = [
            RuntimeError("transient"),
            SimpleNamespace(
                config=SimpleNamespace(
                    params=SimpleNamespace(
                        vectors={NAMED_DENSE_VECTOR: SimpleNamespace(size=768)},
                        sparse_vectors={NAMED_SPARSE_VECTOR: object()},
                    )
                )
            ),
        ]

        assert vector_db.collection_layout("kb_x", client=client) == "missing"
        assert vector_db.collection_layout("kb_x", client=client) == "hybrid"

    def test_result_is_cached(self):
        client = self._client(sparse_names=[NAMED_SPARSE_VECTOR])
        vector_db.collection_layout("kb_x", client=client)
        vector_db.collection_layout("kb_x", client=client)
        assert client.get_collection.call_count == 1, "未命中缓存，每次检索都会多一次往返"

    def test_reset_cache_forces_reprobe(self):
        client = self._client(sparse_names=[NAMED_SPARSE_VECTOR])
        vector_db.collection_layout("kb_x", client=client)
        vector_db.reset_layout_cache()
        vector_db.collection_layout("kb_x", client=client)
        assert client.get_collection.call_count == 2


class TestCollectionUpgradeGuard:
    def test_hybrid_request_on_legacy_collection_is_rejected(self, monkeypatch):
        """向匿名稠密集合请求混合布局不得静默通过（Qdrant 无法原地追加稀疏向量）"""
        client = MagicMock()
        client.get_collections.return_value = SimpleNamespace(
            collections=[SimpleNamespace(name="kb_x")]
        )
        client.get_collection.return_value = SimpleNamespace(
            config=SimpleNamespace(
                params=SimpleNamespace(
                    vectors=SimpleNamespace(size=768), sparse_vectors=None
                )
            )
        )
        monkeypatch.setattr(vector_db, "get_qdrant_client", lambda: client)

        with pytest.raises(ValueError, match="cannot be upgraded in place"):
            vector_db.get_or_create_collection("x", vector_size=768, hybrid=True)

    def test_hybrid_creation_passes_sparse_config(self, monkeypatch):
        client = MagicMock()
        client.get_collections.return_value = SimpleNamespace(collections=[])
        monkeypatch.setattr(vector_db, "get_qdrant_client", lambda: client)

        name = vector_db.get_or_create_collection("y", vector_size=768, hybrid=True)

        assert name == "kb_y"
        kwargs = client.create_collection.call_args.kwargs
        assert NAMED_SPARSE_VECTOR in kwargs["sparse_vectors_config"]
        assert NAMED_DENSE_VECTOR in kwargs["vectors_config"]

    def test_legacy_creation_does_not_pass_sparse_config(self, monkeypatch):
        """既有路径的建表参数必须保持不变"""
        client = MagicMock()
        client.get_collections.return_value = SimpleNamespace(collections=[])
        monkeypatch.setattr(vector_db, "get_qdrant_client", lambda: client)

        vector_db.get_or_create_collection("z", vector_size=768)

        kwargs = client.create_collection.call_args.kwargs
        assert "sparse_vectors_config" not in kwargs
        assert isinstance(kwargs["vectors_config"], object)


class TestCollectionNameHelper:
    def test_single_source_of_naming(self):
        assert vector_db.collection_name_for("abc") == "kb_abc"
