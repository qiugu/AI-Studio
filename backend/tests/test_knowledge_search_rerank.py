"""``KnowledgeBaseService.search`` 的精排集成测试

关注的不是精排质量（那是评测集的职责），而是**集成契约**：

* 关闭精排**且关闭内容去重**时与改造前严格等价（只查 top_k 条、不做任何重排）；
  这条等价路径必须显式保留并断言，否则去重叠加精排后再也无法判断回归来自哪一层；
* 开启精排时按 ``candidate_k`` 宽召回，且返回顺序与展示分数一致；
* 精排不可用时**回落**而非让检索失败——权重缺失不应导致知识库整体不可用。

内容去重本身（折叠、``duplicate_count``、超额召回）由
``tests/test_knowledge_search_dedup.py`` 单独覆盖，本文件只断言它与精排的边界。

全部依赖以替身注入，不连 Qdrant、不加载真实模型。
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.core.vector_db import RetrievedPoint
from app.services.knowledge import KnowledgeBaseService, _sigmoid
from app.utils.reranker import CrossEncoderReranker
from tests._chunk_doubles import chunk_double
from tests._repo_doubles import chunk_repo_double

KB_ID = "11111111-2222-3333-4444-555555555555"
TENANT = "tenant-1"

VECTORS = ["v1", "v2", "v3", "v4", "v5"]
# 内容长度刻意各不相同，使替身 encoder 的排序与稠密相似度顺序**不重合**：
# 若长度一致，重排后仍是原顺序，排序断言将失去区分度。
CONTENTS = {
    "v1": "段落一",
    "v2": "段落二是明显更长的内容",
    "v3": "段落三",
    "v4": "段落四的内容长度是最长的那一档",
    "v5": "段落五",
}
#: 按内容长度降序的期望顺序：v4(14) > v2(10) > v1/v3/v5(3，同分保持召回顺序)
EXPECTED_RERANK_ORDER = ["v4", "v2", "v1", "v3", "v5"]


class FakeEncoder:
    """按「内容长度」打分，使排序可预测且与相似度顺序不同"""

    def predict(self, sentences, **_kwargs):
        return [float(len(passage)) for _query, passage in sentences]


def _build_service():
    """构造只依赖替身的服务实例"""
    chunks_by_vector = {
        vector_id: chunk_double(
            id=f"chunk-{vector_id}",
            vector_id=vector_id,
            content=CONTENTS[vector_id],
            doc_id="doc-1",
            document=SimpleNamespace(file_name="doc.pdf"),
            chunk_index=index,
        )
        for index, vector_id in enumerate(VECTORS)
    }

    service = KnowledgeBaseService(db=MagicMock(), tenant_id=TENANT)
    service.get_knowledge_base = lambda _kb_id: SimpleNamespace(
        id=KB_ID, tenant_id=TENANT, embedding_model="fake/model", active_collection=None
    )
    service.chunk_repo = chunk_repo_double(chunks_by_vector.values())
    return service


@pytest.fixture
def patched(monkeypatch, config_defaults):
    """替换向量化与 Qdrant 召回，并记录调用参数"""
    captured = {"search_calls": []}

    monkeypatch.setattr(
        "app.services.knowledge.get_embedding_client",
        lambda **_kwargs: SimpleNamespace(embed=lambda texts: [[0.1, 0.2, 0.3] for _ in texts]),
    )

    def fake_search_points(**kwargs):
        captured["search_calls"].append(kwargs)
        dense_order = captured["dense_order"]
        return [
            RetrievedPoint(id=vector_id, score=1.0 - index * 0.1)
            for index, vector_id in enumerate(dense_order[: kwargs["limit"]])
        ]

    captured["dense_order"] = VECTORS
    monkeypatch.setattr("app.services.knowledge.search_points", fake_search_points)
    return captured


@pytest.fixture
def config_defaults(monkeypatch):
    """把精排与去重相关配置复位到默认，避免用例之间相互污染"""
    from app.core import config as config_module

    monkeypatch.setattr(config_module.config, "reranker_enabled", False, raising=False)
    monkeypatch.setattr(config_module.config, "reranker_candidate_k", 20, raising=False)
    monkeypatch.setattr(config_module.config, "retrieval_score_threshold", 0.0, raising=False)
    monkeypatch.setattr(config_module.config, "retrieval_dedup_enabled", True, raising=False)
    monkeypatch.setattr(config_module.config, "retrieval_fetch_multiplier", 2, raising=False)
    return config_module.config


class TestRerankDisabled:
    def test_dedup_disabled_queries_only_top_k(self, patched, config_defaults):
        """关闭去重：只查 top_k 条、不做任何重排——与改造前严格等价的回归基线"""
        config_defaults.retrieval_dedup_enabled = False
        service = _build_service()
        result = service.search(KB_ID, "查询", top_k=2)

        assert patched["search_calls"][0]["limit"] == 2
        assert [item["id"] for item in result] == ["chunk-v1", "chunk-v2"]
        assert all("rerank_score" not in item for item in result)

    def test_dedup_enabled_widens_recall(self, patched, config_defaults):
        """开启去重：召回量必须按倍数放大（折叠细节见去重专用测试文件）"""
        service = _build_service()
        result = service.search(KB_ID, "查询", top_k=2)

        assert patched["search_calls"][0]["limit"] == 2 * config_defaults.retrieval_fetch_multiplier
        assert all("rerank_score" not in item for item in result)

    def test_score_equals_retrieval_score_without_rerank(self, patched, config_defaults):
        service = _build_service()
        result = service.search(KB_ID, "查询", top_k=3)

        for item in result:
            assert item["score"] == item["retrieval_score"]

    def test_explicit_false_overrides_enabled_config(self, patched, config_defaults):
        # 关闭去重，使本用例只考察「显式入参覆盖配置」这一件事，
        # 不把召回量断言与去重的超额召回混在一起。
        config_defaults.retrieval_dedup_enabled = False
        config_defaults.reranker_enabled = True
        service = _build_service()
        service.search(KB_ID, "查询", top_k=2, use_rerank=False)

        assert patched["search_calls"][0]["limit"] == 2


class TestRerankEnabled:
    @pytest.fixture
    def fake_reranker(self, monkeypatch):
        """注入真实 CrossEncoderReranker + 替身 encoder，验证的仍是排序契约"""
        reranker = CrossEncoderReranker(model_name="fake/reranker", encoder=FakeEncoder())
        monkeypatch.setattr("app.services.knowledge.get_reranker", lambda **_kwargs: reranker)
        return reranker

    def test_widens_recall_to_candidate_k(self, patched, config_defaults, fake_reranker):
        """开启精排必须宽召回：精排只能重排已召回的候选，候选集过小会限制上限"""
        service = _build_service()
        service.search(KB_ID, "查询", top_k=2, use_rerank=True, candidate_k=5)

        assert patched["search_calls"][0]["limit"] == 5

    def test_candidate_k_never_below_top_k(self, patched, config_defaults, fake_reranker):
        # 关闭去重：本用例考察的是「candidate_k 不得低于 top_k」，
        # 开启去重后召回量会再被放大，断言会失去区分度。
        config_defaults.retrieval_dedup_enabled = False
        service = _build_service()
        service.search(KB_ID, "查询", top_k=4, use_rerank=True, candidate_k=2)

        assert patched["search_calls"][0]["limit"] == 4

    def test_truncates_to_top_k_after_rerank(self, patched, config_defaults, fake_reranker):
        service = _build_service()
        result = service.search(KB_ID, "查询", top_k=2, use_rerank=True, candidate_k=5)

        assert len(result) == 2

    def test_order_follows_rerank_scores(self, patched, config_defaults, fake_reranker):
        """重排结果必须与稠密顺序不同，否则本用例无法证明重排确实生效"""
        service = _build_service()
        result = service.search(KB_ID, "查询", top_k=3, use_rerank=True, candidate_k=5)

        assert [item["id"] for item in result] == ["chunk-v4", "chunk-v2", "chunk-v1"]
        rerank_scores = [item["rerank_score"] for item in result]
        assert rerank_scores == sorted(rerank_scores, reverse=True)

    def test_score_is_monotonic_with_returned_order(self, patched, config_defaults, fake_reranker):
        """展示分数必须与返回顺序单调一致，否则界面上的分数与排序互相矛盾"""
        service = _build_service()
        result = service.search(KB_ID, "查询", top_k=4, use_rerank=True, candidate_k=5)

        scores = [item["score"] for item in result]
        assert scores == sorted(scores, reverse=True)
        assert all(0.0 < score < 1.0 for score in scores)

    def test_preserves_retrieval_score_for_diagnosis(self, patched, config_defaults, fake_reranker):
        """保留稠密相似度，才能区分『召回没捞到』与『捞到了但排太后』"""
        service = _build_service()
        result = service.search(KB_ID, "查询", top_k=3, use_rerank=True, candidate_k=5)

        for item in result:
            assert "retrieval_score" in item
            assert item["score"] != item["retrieval_score"] or item["rerank_score"] == 0.0
            assert item["score"] == pytest.approx(_sigmoid(item["rerank_score"]))

    def test_single_candidate_skips_rerank(self, patched, config_defaults, fake_reranker):
        """只有一个候选时重排没有意义，不应付出推理成本"""
        patched["dense_order"] = ["v1"]
        service = _build_service()
        result = service.search(KB_ID, "查询", top_k=1, use_rerank=True, candidate_k=5)

        assert all("rerank_score" not in item for item in result)

    def test_config_default_enables_rerank(self, patched, config_defaults, fake_reranker):
        config_defaults.reranker_enabled = True
        service = _build_service()
        service.search(KB_ID, "查询", top_k=2)

        assert patched["search_calls"][0]["limit"] == config_defaults.reranker_candidate_k


class TestRerankDegradation:
    def test_unavailable_reranker_falls_back_to_dense(self, patched, config_defaults, monkeypatch, caplog):
        """精排是增强：模型不可用时必须回落，而不是让知识库整体不可用"""
        from app.utils.reranker import RerankerUnavailable

        class Broken:
            def rerank(self, *_args, **_kwargs):
                raise RerankerUnavailable("weights missing")

        monkeypatch.setattr("app.services.knowledge.get_reranker", lambda **_kwargs: Broken())
        service = _build_service()

        with caplog.at_level(logging.WARNING, logger="app.services.knowledge"):
            result = service.search(KB_ID, "查询", top_k=3, use_rerank=True, candidate_k=5)

        assert [item["id"] for item in result] == ["chunk-v1", "chunk-v2", "chunk-v3"]
        assert all("rerank_score" not in item for item in result)
        assert any("Reranker unavailable" in record.message for record in caplog.records)


class TestEdgeCases:
    def test_empty_query_rejected(self, patched, config_defaults):
        from app.core.exceptions import ValidationException

        service = _build_service()
        with pytest.raises(ValidationException):
            service.search(KB_ID, "   ", top_k=2)

    def test_qdrant_failure_returns_empty(self, patched, config_defaults, monkeypatch, caplog):
        def _explode(**_kwargs):
            raise RuntimeError("qdrant down")

        monkeypatch.setattr("app.services.knowledge.search_points", _explode)
        service = _build_service()

        with caplog.at_level(logging.WARNING, logger="app.services.knowledge"):
            assert service.search(KB_ID, "查询", top_k=2) == []

    def test_missing_chunk_rows_are_skipped(self, patched, config_defaults, monkeypatch):
        """Qdrant 命中的 point 在 MySQL 中不存在时应跳过，而不是抛错"""
        monkeypatch.setattr(
            "app.services.knowledge.get_embedding_client",
            lambda **_kwargs: SimpleNamespace(embed=lambda texts: [[0.1] for _ in texts]),
        )
        monkeypatch.setattr(
            "app.services.knowledge.search_points",
            lambda **_kwargs: [RetrievedPoint(id="ghost", score=0.9)],
        )
        service = _build_service()
        assert service.search(KB_ID, "查询", top_k=2) == []
