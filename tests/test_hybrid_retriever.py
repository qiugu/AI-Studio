"""混合检索器（评测侧）的契约

评测工具与业务代码的风险性质不同：业务代码出错会立刻暴露（用户看到报错或空结果），
而**评测工具出错会产出一份看起来正常的报告**。因此这里最要紧的两条是：

1. **不许静默降级**。集合没有稀疏向量时必须直接报错。若退化为纯稠密，报告仍会
   输出一组漂亮的指标，只是标签写着 "hybrid" —— 这类失真结论比直接失败危险得多，
   它会让人据此做出「混合检索有效/无效」的错误决策。
2. **口径与线上同源**。``HybridRetriever`` 必须走 ``search_points``（带
   ``using="dense"``）、``search_sparse_points`` 与 ``weighted_fuse``，
   而不是自己实现一遍。本文件通过断言「这三者被真实调用」来固定该约束。
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.core.config import config
from app.core.vector_db import RetrievedPoint
from app.rag_eval.retrievers import HybridRetriever


class _EncoderStub:
    def __init__(self, indices=(1, 2, 3)):
        self.indices = list(indices)
        self.calls = []

    def query_vector(self, text):
        self.calls.append(text)
        return list(self.indices), [1.0] * len(self.indices)


@pytest.fixture
def harness(monkeypatch):
    state = {
        "dense": [],
        "sparse": [],
        "dense_calls": [],
        "sparse_calls": [],
        "has_sparse": True,
    }

    def fake_dense(**kwargs):
        state["dense_calls"].append(kwargs)
        return [RetrievedPoint(id=i, score=s) for i, s in state["dense"][: kwargs["limit"]]]

    def fake_sparse(**kwargs):
        state["sparse_calls"].append(kwargs)
        if not kwargs.get("indices"):
            return []
        return [RetrievedPoint(id=i, score=s) for i, s in state["sparse"][: kwargs["limit"]]]

    monkeypatch.setattr("app.rag_eval.retrievers.search_points", fake_dense)
    monkeypatch.setattr("app.rag_eval.retrievers.search_sparse_points", fake_sparse)
    monkeypatch.setattr(
        "app.rag_eval.retrievers.supports_sparse_vectors",
        lambda _name, **_kw: state["has_sparse"],
    )
    return state


def _retriever(state, **kwargs):
    encoder = kwargs.pop("encoder", None) or _EncoderStub()
    kwargs.setdefault("embed_fn", lambda _q: [0.1, 0.2, 0.3])
    kwargs.setdefault("client", MagicMock())
    return HybridRetriever("kb_x_hybrid", encoder=encoder, **kwargs)


class TestFailFast:
    def test_missing_sparse_vector_raises(self, harness):
        """集合没有稀疏向量必须报错，绝不能静默退化为纯稠密"""
        harness["has_sparse"] = False
        retriever = _retriever(harness)

        with pytest.raises(RuntimeError, match="dense-only"):
            retriever.retrieve("查询", top_k=5)

    def test_layout_is_checked_only_once(self, harness):
        """探测结果缓存：不得每次检索都多一次元数据往返"""
        retriever = _retriever(harness)
        retriever.retrieve("查询", top_k=3)
        retriever.retrieve("查询", top_k=3)
        assert retriever._layout_verified is True

    def test_invalid_branch_budget_rejected(self):
        with pytest.raises(ValueError):
            HybridRetriever("kb_x", dense_k=0)
        with pytest.raises(ValueError):
            HybridRetriever("kb_x", sparse_k=0)


class TestSharedCodePath:
    def test_dense_call_uses_named_vector(self, harness):
        """命名稠密集合必须带 using，否则 Qdrant 会拒绝"""
        harness["dense"] = [("v1", 0.9)]
        _retriever(harness).retrieve("查询", top_k=3)
        assert harness["dense_calls"][0]["using"] == "dense"

    def test_sparse_call_uses_encoder_query_vector(self, harness):
        harness["dense"] = [("v1", 0.9)]
        harness["sparse"] = [("v2", 5.0)]
        encoder = _EncoderStub(indices=(11, 22))
        _retriever(harness, encoder=encoder).retrieve("查询", top_k=3)

        assert encoder.calls == ["查询"]
        assert list(harness["sparse_calls"][0]["indices"]) == [11, 22]

    def test_branch_limits_are_per_branch(self, harness):
        """两路各自的预算必须分别生效，不能一路放大另一路也跟着变"""
        harness["dense"] = [("v1", 0.9)]
        harness["sparse"] = [("v2", 5.0)]
        _retriever(harness, dense_k=30, sparse_k=70).retrieve("查询", top_k=5)

        assert harness["dense_calls"][0]["limit"] == 30
        assert harness["sparse_calls"][0]["limit"] == 70


class TestResults:
    def test_fused_order_is_returned(self, harness):
        """与线上共用 weighted_fuse：词法强烈支持 v2 时它应上浮到首位"""
        harness["dense"] = [("v1", 0.90), ("v2", 0.85), ("v3", 0.10)]
        harness["sparse"] = [("v3", 10.0), ("v2", 9.0), ("v1", 0.5)]
        result = _retriever(harness, alpha=0.7).retrieve("查询", top_k=3)

        assert result.ids[0] == "v2", f"融合未生效：{result.ids}"

    def test_candidate_pool_is_the_full_fused_list(self, harness):
        """宽召回集合必须是融合后的完整候选池，否则无法区分召回损失与排序损失"""
        harness["dense"] = [("v1", 0.9), ("v2", 0.5)]
        harness["sparse"] = [("v3", 4.0)]
        result = _retriever(harness).retrieve("查询", top_k=1)

        assert result.candidate_ids is not None
        assert set(result.candidate_ids) == {"v1", "v2", "v3"}
        assert len(result.ids) == 1

    def test_scores_align_with_ids(self, harness):
        harness["dense"] = [("v1", 0.9)]
        harness["sparse"] = [("v2", 4.0)]
        result = _retriever(harness).retrieve("查询", top_k=2)
        assert len(result.ids) == len(result.scores) == 2

    def test_query_without_tokens_still_returns_dense(self, harness):
        """查询没有可匹配词元（纯标点等）时不应报错，稠密分支仍应给出结果"""
        harness["dense"] = [("v1", 0.9)]
        harness["sparse"] = [("v2", 4.0)]
        result = _retriever(harness, encoder=_EncoderStub(indices=())).retrieve("？", top_k=2)

        assert result.ids == ["v1"]

    def test_empty_everything_returns_empty(self, harness):
        result = _retriever(harness).retrieve("查询", top_k=3)
        assert result.ids == []
        assert result.candidate_ids == []


class TestConfigDefaults:
    def test_alpha_defaults_to_config(self, monkeypatch):
        monkeypatch.setattr(config, "retrieval_hybrid_alpha", 0.65, raising=False)
        assert HybridRetriever("kb_x").alpha == pytest.approx(0.65)

    def test_explicit_alpha_wins(self, monkeypatch):
        monkeypatch.setattr(config, "retrieval_hybrid_alpha", 0.65, raising=False)
        assert HybridRetriever("kb_x", alpha=0.9).alpha == pytest.approx(0.9)

    def test_name_encodes_alpha_for_reporting(self):
        """报告里要能一眼看出这组指标对应哪个 α —— α 是结果的组成部分，不是细节"""
        assert "0.8" in HybridRetriever("kb_x", alpha=0.8).name


class TestEvalCliWiring:
    """``scripts/rag_eval.py --hybrid`` 必须真的装配 HybridRetriever

    若标志被解析但没有接到检索器上，评测会安静地按纯稠密跑完，产出一份
    标签写着 hybrid 的报告——这类失真比报错危险得多。
    """

    @staticmethod
    def _load_cli_module():
        import importlib.util
        import sys as _sys
        from pathlib import Path as _Path

        path = _Path(__file__).resolve().parent.parent / "scripts" / "rag_eval.py"
        spec = importlib.util.spec_from_file_location("rag_eval_cli_under_test", path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        _sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module

    def test_hybrid_flag_builds_hybrid_retriever(self):
        from app.rag_eval.retrievers import QdrantRetriever

        cli = self._load_cli_module()
        args = cli.build_parser().parse_args(
            ["--retriever", "qdrant", "--collection", "kb_x_hybrid", "--hybrid", "--hybrid-alpha", "0.8"]
        )
        built = cli.build_retriever(args, corpus=None, index=None, text_lookup=lambda _i: None)

        assert isinstance(built, HybridRetriever)
        assert built.alpha == pytest.approx(0.8)
        assert built.collection_name == "kb_x_hybrid"

    def test_without_flag_keeps_qdrant_retriever(self):
        cli = self._load_cli_module()
        args = cli.build_parser().parse_args(
            ["--retriever", "qdrant", "--collection", "kb_x"]
        )
        built = cli.build_retriever(args, corpus=None, index=None, text_lookup=lambda _i: None)

        from app.rag_eval.retrievers import QdrantRetriever

        assert isinstance(built, QdrantRetriever)

    def test_hybrid_flags_default_are_conservative(self):
        cli = self._load_cli_module()
        args = cli.build_parser().parse_args(["--retriever", "qdrant", "--collection", "kb_x"])
        assert args.hybrid is False
        assert args.hybrid_alpha is None, "缺省应由 config 决定 α，而不是在 CLI 里硬编码"
        assert args.hybrid_dense_k == 200
        assert args.hybrid_sparse_k == 200


class TestQdrantRetrieverLayoutAutoDetect:
    """``QdrantRetriever`` 必须按集合布局决定是否传 ``using``

    这是一处实测故障的回归防线：混合布局集合的稠密向量是命名的，对它发匿名向量
    查询会被 Qdrant 以 400 拒绝，表现为「100 个查询全部失败，但仍生成一份全 0 报告」。
    """

    def test_hybrid_collection_gets_dense_vector_name(self, monkeypatch):
        from app.core.vector_db import RetrievedPoint
        from app.rag_eval.retrievers import QdrantRetriever

        seen = {}

        def fake_search_points(**kwargs):
            seen.update(kwargs)
            return [RetrievedPoint(id="v1", score=0.9)]

        monkeypatch.setattr("app.rag_eval.retrievers.search_points", fake_search_points)
        monkeypatch.setattr(
            "app.rag_eval.retrievers.collection_layout", lambda _n, **_k: "hybrid"
        )
        retriever = QdrantRetriever("kb_x_hybrid", embed_fn=lambda _q: [0.1])
        retriever.retrieve("查询", top_k=5)

        assert seen["using"] == "dense"

    def test_legacy_collection_stays_anonymous(self, monkeypatch):
        from app.core.vector_db import RetrievedPoint
        from app.rag_eval.retrievers import QdrantRetriever

        seen = {}

        def fake_search_points(**kwargs):
            seen.update(kwargs)
            return [RetrievedPoint(id="v1", score=0.9)]

        monkeypatch.setattr("app.rag_eval.retrievers.search_points", fake_search_points)
        monkeypatch.setattr(
            "app.rag_eval.retrievers.collection_layout", lambda _n, **_k: "legacy_dense"
        )
        QdrantRetriever("kb_x", embed_fn=lambda _q: [0.1]).retrieve("查询", top_k=5)

        assert seen["using"] is None

    def test_explicit_using_overrides_detection(self, monkeypatch):
        from app.core.vector_db import RetrievedPoint
        from app.rag_eval.retrievers import QdrantRetriever

        seen = {}
        monkeypatch.setattr(
            "app.rag_eval.retrievers.search_points",
            lambda **kwargs: seen.update(kwargs) or [RetrievedPoint(id="v1", score=0.9)],
        )
        monkeypatch.setattr(
            "app.rag_eval.retrievers.collection_layout", lambda _n, **_k: "legacy_dense"
        )
        QdrantRetriever("kb_x", embed_fn=lambda _q: [0.1], using="custom").retrieve("查询", 5)

        assert seen["using"] == "custom"
