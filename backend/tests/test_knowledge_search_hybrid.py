"""``KnowledgeBaseService.search`` 的混合检索分支契约

混合检索是**可选增强**，因此这里的核心不是「融合算得对不对」（那由
``test_retrieval_fusion.py`` 覆盖），而是**降级边界必须精确**：

* 开关关闭 → 行为必须与改造前**严格等价**（同样的顺序、同样的分数、同样只查一路）。
  这是「可以安全默认关闭」的全部依据；一旦不等价，开启开关就成了不可回滚的操作。
* 开关打开但该库**未回填** → 退化为纯稠密，而不是抛 ``Not existing vector name error``
  把一次本来可用的检索变成 500。
* 词法分支**自身失败** → 只降级该分支。增强环节的单点故障不得升级为功能整体不可用，
  这与精排降级的处理原则一致。
* ``retrieval_score`` 的语义必须可解释：词法独有项没有稠密相似度，此时**不给字段**
  而不是填 0.0（0.0 会把「稠密没召回到」误读成「稠密认为它完全不相关」）。

全部依赖以替身注入，不连 Qdrant、不连 MySQL、不加载真实模型。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.core.vector_db import RetrievedPoint
from app.services.knowledge import KnowledgeBaseService

KB_ID = "11111111-2222-3333-4444-555555555555"
TENANT = "tenant-1"


def _build_service(contents: dict[str, str]) -> KnowledgeBaseService:
    """按 ``{vector_id: 内容}`` 构造只依赖替身的服务实例"""
    chunks = {
        vector_id: SimpleNamespace(
            id=f"chunk-{vector_id}",
            vector_id=vector_id,
            content=content,
            doc_id="doc-1",
            document=SimpleNamespace(file_name="doc.pdf"),
            chunk_index=index,
            source_page=None,
            heading_path=None,
        )
        for index, (vector_id, content) in enumerate(contents.items())
    }

    service = KnowledgeBaseService(db=MagicMock(), tenant_id=TENANT)
    service.get_knowledge_base = lambda _kb_id: SimpleNamespace(
        id=KB_ID, tenant_id=TENANT, embedding_model="fake/model", active_collection=None
    )
    service.chunk_repo = SimpleNamespace(
        list_by_vector_ids=lambda ids: [chunks[v] for v in ids if v in chunks]
    )
    return service


@pytest.fixture
def config_defaults(monkeypatch):
    """把检索相关配置复位到默认，避免用例之间相互污染"""
    from app.core import config as config_module

    monkeypatch.setattr(config_module.config, "reranker_enabled", False, raising=False)
    monkeypatch.setattr(config_module.config, "retrieval_score_threshold", 0.0, raising=False)
    monkeypatch.setattr(config_module.config, "retrieval_dedup_enabled", True, raising=False)
    monkeypatch.setattr(config_module.config, "retrieval_fetch_multiplier", 2, raising=False)
    monkeypatch.setattr(config_module.config, "retrieval_hybrid_enabled", False, raising=False)
    monkeypatch.setattr(config_module.config, "retrieval_hybrid_alpha", 0.7, raising=False)
    monkeypatch.setattr(config_module.config, "retrieval_sparse_top_k", 50, raising=False)
    return config_module.config


@pytest.fixture
def harness(monkeypatch):
    """替换向量化、两路召回与布局探测，并记录调用情况"""
    state: dict = {
        "dense": [],       # [(id, score)]
        "sparse": [],      # [(id, score)]
        "dense_calls": [],
        "sparse_calls": [],
        "layout": "hybrid",
        "dense_error": None,
        "sparse_error": None,
    }

    monkeypatch.setattr(
        "app.services.knowledge.get_embedding_client",
        lambda **_kwargs: SimpleNamespace(embed=lambda texts: [[0.1, 0.2, 0.3] for _ in texts]),
    )

    def fake_search_points(**kwargs):
        state["dense_calls"].append(kwargs)
        if state["dense_error"] is not None:
            raise state["dense_error"]
        return [RetrievedPoint(id=i, score=s) for i, s in state["dense"][: kwargs["limit"]]]

    def fake_search_sparse_points(**kwargs):
        state["sparse_calls"].append(kwargs)
        if state["sparse_error"] is not None:
            raise state["sparse_error"]
        return [RetrievedPoint(id=i, score=s) for i, s in state["sparse"][: kwargs["limit"]]]

    monkeypatch.setattr("app.services.knowledge.search_points", fake_search_points)
    monkeypatch.setattr(
        "app.services.knowledge.search_sparse_points", fake_search_sparse_points
    )
    monkeypatch.setattr(
        "app.services.knowledge.collection_layout",
        lambda _name, **_kw: state["layout"],
    )
    monkeypatch.setattr(
        "app.services.knowledge.default_encoder",
        lambda: SimpleNamespace(query_vector=lambda _q: ([1, 2], [1.0, 1.0])),
    )
    return state


class TestLayoutDrivesUsing:
    """布局决定 ``using``，开关决定是否融合——二者必须解耦

    这是一处**实测踩到的真实故障**：在混合布局集合上跑纯稠密评测时，
    因未传 ``using="dense"``，Qdrant 对匿名向量查询返回 400，
    100/100 查询全部失败，而报告仍正常生成一份全 0 指标。
    """

    def test_hybrid_layout_forces_named_dense_even_when_flag_off(self, harness, config_defaults):
        """开关关闭但集合是混合布局 → 仍须以 using="dense" 查询"""
        config_defaults.retrieval_hybrid_enabled = False
        harness["layout"] = "hybrid"
        harness["dense"] = [("v1", 0.9)]
        service = _build_service({"v1": "内容1"})

        service.search_with_diagnostics(KB_ID, "查询", top_k=1)

        assert harness["dense_calls"][0]["using"] == "dense"
        assert harness["sparse_calls"] == [], "开关关闭时不得跑词法分支"

    def test_legacy_layout_keeps_anonymous_query(self, harness, config_defaults):
        """旧布局必须继续发匿名查询，否则既有库会全线 400"""
        harness["layout"] = "legacy_dense"
        harness["dense"] = [("v1", 0.9)]
        service = _build_service({"v1": "内容1"})

        service.search_with_diagnostics(KB_ID, "查询", top_k=1)

        assert harness["dense_calls"][0]["using"] is None

    def test_missing_layout_keeps_anonymous_query(self, harness, config_defaults):
        harness["layout"] = "missing"
        harness["dense"] = [("v1", 0.9)]
        service = _build_service({"v1": "内容1"})

        service.search_with_diagnostics(KB_ID, "查询", top_k=1)

        assert harness["dense_calls"][0]["using"] is None


class TestHybridDisabled:
    def test_matches_legacy_behaviour_exactly(self, harness, config_defaults):
        """开关关闭 + 旧布局时必须与改造前逐位一致：顺序、分数、只查一路、不传 using"""
        harness["layout"] = "legacy_dense"
        harness["dense"] = [("v1", 0.9), ("v2", 0.8), ("v3", 0.7)]
        harness["sparse"] = [("v3", 99.0), ("v1", 50.0)]
        service = _build_service({f"v{i}": f"内容{i}" for i in (1, 2, 3)})

        outcome = service.search_with_diagnostics(KB_ID, "查询", top_k=3)

        assert [item["id"] for item in outcome.results] == ["chunk-v1", "chunk-v2", "chunk-v3"]
        assert [item["score"] for item in outcome.results] == [0.9, 0.8, 0.7]
        # 纯稠密路径下 score 与 retrieval_score 必须相等
        assert all(item["score"] == item["retrieval_score"] for item in outcome.results)
        assert harness["sparse_calls"] == [], "开关关闭时不得发起词法查询"

    def test_dense_call_omits_using_on_legacy_collection(self, harness, config_defaults):
        """旧布局集合不得传 using —— 匿名向量集合收到 using 会直接报错"""
        harness["layout"] = "legacy_dense"
        harness["dense"] = [("v1", 0.9)]
        service = _build_service({"v1": "内容"})

        service.search_with_diagnostics(KB_ID, "查询", top_k=3)

        assert harness["dense_calls"][0]["using"] is None


class TestHybridEnabledButNotBackfilled:
    def test_degrades_to_dense_only(self, harness, config_defaults):
        """开关已开但该库未回填 → 退化为纯稠密，而不是报错"""
        config_defaults.retrieval_hybrid_enabled = True
        harness["layout"] = "legacy_dense"
        harness["dense"] = [("v1", 0.9), ("v2", 0.8)]
        service = _build_service({"v1": "内容1", "v2": "内容2"})

        outcome = service.search_with_diagnostics(KB_ID, "查询", top_k=2)

        assert [item["id"] for item in outcome.results] == ["chunk-v1", "chunk-v2"]
        assert outcome.degraded is False
        assert harness["sparse_calls"] == [], "集合没有稀疏向量时不得发起词法查询"
        assert harness["dense_calls"][0]["using"] is None


class TestHybridEnabled:
    def test_sparse_branch_runs_and_drives_order(self, harness, config_defaults):
        """开关打开且已回填：两路都跑，融合结果决定最终顺序

        注意候选数不能取 2：min-max 归一化在两点上的取值必然是 {1.0, 0.0}，
        此时「谁第一」只由各分支的头部决定，融合退化成纯粹的排名交换，
        无法体现加权融合的作用。生产侧的候选池是 50~200 条，不存在该退化。
        """
        config_defaults.retrieval_hybrid_enabled = True
        # 稠密：v1 略高于 v2；词法：v3 最高、v2 次之、v1 几乎为零。
        # 融合后 v2 应升到第一（稠密次高 + 词法次高），v1 退居第二。
        harness["dense"] = [("v1", 0.90), ("v2", 0.85), ("v3", 0.10)]
        harness["sparse"] = [("v3", 10.0), ("v2", 9.0), ("v1", 0.5)]
        service = _build_service({"v1": "内容1", "v2": "内容2", "v3": "内容3"})

        outcome = service.search_with_diagnostics(KB_ID, "查询", top_k=3)

        assert harness["sparse_calls"], "开关打开且已回填时必须发起词法查询"
        assert harness["dense_calls"][0]["using"] == "dense"
        order = [item["id"] for item in outcome.results]
        assert order == ["chunk-v2", "chunk-v1", "chunk-v3"], f"融合未改变顺序：{order}"

    def test_sparse_only_item_has_no_retrieval_score(self, harness, config_defaults):
        """词法独有项不得给出 retrieval_score —— 缺失比 0.0 更诚实"""
        config_defaults.retrieval_hybrid_enabled = True
        harness["dense"] = [("v1", 0.9)]
        harness["sparse"] = [("v9", 8.0)]
        service = _build_service({"v1": "内容1", "v9": "仅词法命中"})

        outcome = service.search_with_diagnostics(KB_ID, "查询", top_k=5)

        by_id = {item["id"]: item for item in outcome.results}
        assert "chunk-v9" in by_id, "词法独有项被丢弃，混合检索的收益随之消失"
        assert "retrieval_score" not in by_id["chunk-v9"]
        assert by_id["chunk-v1"]["retrieval_score"] == pytest.approx(0.9)

    def test_fused_score_differs_from_dense_score(self, harness, config_defaults):
        """融合生效时 ``score`` 不再是稠密相似度，调用方不得再按相似度解读它"""
        config_defaults.retrieval_hybrid_enabled = True
        harness["dense"] = [("v1", 0.9)]
        harness["sparse"] = [("v1", 5.0)]
        service = _build_service({"v1": "内容1"})

        outcome = service.search_with_diagnostics(KB_ID, "查询", top_k=1)

        item = outcome.results[0]
        assert item["retrieval_score"] == pytest.approx(0.9)
        assert item["score"] != item["retrieval_score"]

    def test_sparse_branch_uses_sparse_top_k_budget(self, harness, config_defaults):
        """词法分支的候选池由 ``retrieval_sparse_top_k`` 决定，且不小于稠密的 fetch_k"""
        config_defaults.retrieval_hybrid_enabled = True
        config_defaults.retrieval_sparse_top_k = 77
        config_defaults.retrieval_fetch_multiplier = 1
        harness["dense"] = [("v1", 0.9)]
        harness["sparse"] = []
        service = _build_service({"v1": "内容1"})

        service.search_with_diagnostics(KB_ID, "查询", top_k=5)

        assert harness["sparse_calls"][0]["limit"] == 77
        assert harness["dense_calls"][0]["limit"] == 5


class TestHybridFailureIsolation:
    def test_sparse_failure_falls_back_to_dense(self, harness, config_defaults):
        """词法分支异常不得让整次检索失败——增强环节的故障必须被隔离"""
        config_defaults.retrieval_hybrid_enabled = True
        harness["sparse_error"] = RuntimeError("sparse backend exploded")
        harness["dense"] = [("v1", 0.9), ("v2", 0.8)]
        service = _build_service({"v1": "内容1", "v2": "内容2"})

        outcome = service.search_with_diagnostics(KB_ID, "查询", top_k=2)

        assert outcome.degraded is False
        assert [item["id"] for item in outcome.results] == ["chunk-v1", "chunk-v2"]

    def test_dense_failure_still_reports_degraded(self, harness, config_defaults):
        """稠密分支是主链路，其失败仍按既有契约上报降级（行为不变）"""
        config_defaults.retrieval_hybrid_enabled = True
        harness["dense_error"] = RuntimeError("Collection kb_x not found")
        service = _build_service({"v1": "内容1"})

        outcome = service.search_with_diagnostics(KB_ID, "查询", top_k=2)

        assert outcome.degraded is True
        assert outcome.reason == "collection_not_found"
        assert outcome.results == []
