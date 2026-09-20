"""``KnowledgeBaseService.search`` 的内容去重契约

覆盖的不是「去重算法」本身，而是三条**用户可见的契约**：

* 同一段落的多个等值副本只返回一条，且保留相似度最高的那一条；
* 折叠掉的副本数通过 ``duplicate_count`` 暴露，使「结果条数少于 top_k」可解释；
* 超额召回保证去重不会顺手削掉结果条数——这才是「10 条里一半重复」的正解：
  去重后应尽量补足到 top_k 条**不同**内容，而不是只剩下 5 条。

反面契约同样重要：归一化**不能**过度合并。大小写不同的片段必须保持独立，
否则会把代码语境下确有区别的内容误判成同一段。

全部依赖以替身注入，不连 Qdrant、不连 MySQL、不加载真实模型。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.core.vector_db import RetrievedPoint
from app.services.knowledge import KnowledgeBaseService
from tests._chunk_doubles import chunk_double
from tests._repo_doubles import chunk_repo_double

KB_ID = "11111111-2222-3333-4444-555555555555"
TENANT = "tenant-1"


def _build_service(contents: dict[str, str]) -> KnowledgeBaseService:
    """按 ``{vector_id: 内容}`` 构造只依赖替身的服务实例

    一个 ``vector_id`` 对应一条分块行；不同 ``vector_id`` 携带相同 ``content``
    即模拟「同一段落在库中存在多份等值副本」——这正是重复上传留下的数据形态。
    """
    chunks = {
        vector_id: chunk_double(
            id=f"chunk-{vector_id}",
            vector_id=vector_id,
            content=content,
            doc_id="doc-1",
            document=SimpleNamespace(file_name="Happy-LLM-0727.pdf"),
            chunk_index=index,
        )
        for index, (vector_id, content) in enumerate(contents.items())
    }

    service = KnowledgeBaseService(db=MagicMock(), tenant_id=TENANT)
    service.get_knowledge_base = lambda _kb_id: SimpleNamespace(
        id=KB_ID, tenant_id=TENANT, embedding_model="fake/model", active_collection=None
    )
    service.chunk_repo = chunk_repo_double(chunks.values())
    return service


@pytest.fixture
def config_defaults(monkeypatch):
    """把去重与精排相关配置复位到默认，避免用例之间相互污染"""
    from app.core import config as config_module

    monkeypatch.setattr(config_module.config, "reranker_enabled", False, raising=False)
    monkeypatch.setattr(config_module.config, "retrieval_score_threshold", 0.0, raising=False)
    monkeypatch.setattr(config_module.config, "retrieval_dedup_enabled", True, raising=False)
    monkeypatch.setattr(config_module.config, "retrieval_fetch_multiplier", 2, raising=False)
    return config_module.config


@pytest.fixture
def patched(monkeypatch):
    """替换向量化与 Qdrant 召回，并记录每次召回的 limit

    ``state['dense_order']`` 即召回顺序，分数随之递减（0.9 / 0.85 / ...），
    因此「保留分数最高的副本」等价于「保留 dense_order 中靠前的那一个」。
    """
    state: dict = {"dense_order": []}
    limits: list[int] = []

    monkeypatch.setattr(
        "app.services.knowledge.get_embedding_client",
        lambda **_kwargs: SimpleNamespace(
            embed=lambda texts: [[0.1, 0.2, 0.3] for _ in texts]
        ),
    )

    def fake_search_points(**kwargs):
        limits.append(kwargs["limit"])
        return [
            RetrievedPoint(id=vector_id, score=0.9 - index * 0.05)
            for index, vector_id in enumerate(state["dense_order"][: kwargs["limit"]])
        ]

    monkeypatch.setattr("app.services.knowledge.search_points", fake_search_points)
    return {"state": state, "limits": limits}


class TestContentDedup:
    def test_collapses_equivalent_copies(self, patched, config_defaults):
        """同一段落的两个副本只返回一条——这就是「10 条里一半重复」的直接修复"""
        patched["state"]["dense_order"] = ["v1", "v2"]
        service = _build_service({"v1": "第四章 大语言模型", "v2": "第四章 大语言模型"})

        result = service.search(KB_ID, "查询", top_k=5)

        assert len(result) == 1
        assert result[0]["id"] == "chunk-v1"  # 保留分数更高的那份
        assert result[0]["duplicate_count"] == 1

    def test_blank_differences_count_as_same_content(self, patched, config_defaults):
        """分块边界的空白差异不应被当作不同内容（中文正文的差异几乎都来自空白）"""
        patched["state"]["dense_order"] = ["v1", "v2"]
        service = _build_service({"v1": "第四章  大语言模型\n", "v2": "第四章 大语言模型"})

        result = service.search(KB_ID, "查询", top_k=5)

        assert len(result) == 1
        assert result[0]["duplicate_count"] == 1

    def test_case_differences_are_not_merged(self, patched, config_defaults):
        """大小写折叠属过度合并：Transformer / transformer 在代码语境下可能确有区别"""
        patched["state"]["dense_order"] = ["v1", "v2"]
        service = _build_service({"v1": "Transformer 架构", "v2": "transformer 架构"})

        result = service.search(KB_ID, "查询", top_k=5)

        assert len(result) == 2
        assert [item["duplicate_count"] for item in result] == [0, 0]

    def test_distinct_contents_keep_zero_duplicate_count(self, patched, config_defaults):
        """无副本时必须显式给出 0，界面才能据此判断「本次是否有折叠发生」"""
        patched["state"]["dense_order"] = ["v1", "v2", "v3"]
        service = _build_service({"v1": "段落一", "v2": "段落二", "v3": "段落三"})

        result = service.search(KB_ID, "查询", top_k=5)

        assert [item["id"] for item in result] == ["chunk-v1", "chunk-v2", "chunk-v3"]
        assert all(item["duplicate_count"] == 0 for item in result)

    def test_order_stays_score_descending(self, patched, config_defaults):
        """折叠不得打乱排序：返回顺序仍须与分数单调一致"""
        patched["state"]["dense_order"] = ["v1", "v2", "v3", "v4"]
        service = _build_service({"v1": "内容 A", "v2": "内容 A", "v3": "内容 B", "v4": "内容 C"})

        result = service.search(KB_ID, "查询", top_k=5)

        scores = [item["score"] for item in result]
        assert scores == sorted(scores, reverse=True)
        assert [item["content"] for item in result] == ["内容 A", "内容 B", "内容 C"]


class TestOverFetch:
    def test_over_fetch_backfills_distinct_contents(self, patched, config_defaults):
        """超额召回的核心价值：副本被折叠后，用后续的不同内容补足到 top_k

        构造：top_k=4、multiplier=2 → 召回 8 条；前 4 条是两段内容的各两份副本，
        后 4 条是四段不同内容。去重后共 2 + 4 = 6 条不同内容，截断到 4 条且互不相同。

        若没有超额召回（limit=4），用户看到的将只有 2 条——**结果条数会莫名变少**，
        这是「只去重不放大召回」最典型的错误配方。
        """
        patched["state"]["dense_order"] = ["a1", "a2", "b1", "b2", "c", "d", "e", "f"]
        service = _build_service({
            "a1": "内容 A", "a2": "内容 A",
            "b1": "内容 B", "b2": "内容 B",
            "c": "内容 C", "d": "内容 D", "e": "内容 E", "f": "内容 F",
        })

        result = service.search(KB_ID, "查询", top_k=4)

        assert patched["limits"][0] == 8
        assert [item["content"] for item in result] == ["内容 A", "内容 B", "内容 C", "内容 D"]

    def test_multiplier_one_keeps_recall_equal_to_top_k(self, patched, config_defaults):
        """倍数=1 时召回量与关闭去重一致：不引入额外 Qdrant 成本的降级选项"""
        config_defaults.retrieval_fetch_multiplier = 1
        patched["state"]["dense_order"] = ["v1", "v2", "v3"]
        service = _build_service({"v1": "段落一", "v2": "段落二", "v3": "段落三"})

        service.search(KB_ID, "查询", top_k=3)

        assert patched["limits"][0] == 3

    def test_returns_fewer_than_top_k_without_faking_results(self, patched, config_defaults):
        """折叠后不足 top_k 时返回实际条数——不得回填重复项充数"""
        patched["state"]["dense_order"] = ["v1", "v2", "v3", "v4"]
        service = _build_service({v: "同一段内容" for v in ["v1", "v2", "v3", "v4"]})

        result = service.search(KB_ID, "查询", top_k=10)

        assert len(result) == 1
        assert result[0]["duplicate_count"] == 3


class TestDedupOptOut:
    def test_disabled_keeps_duplicates_untouched(self, patched, config_defaults):
        """关闭去重后副本原样返回，且不产出 duplicate_count 字段

        保留该开关是为了能一键回到改造前的行为做对照——对照通路必须可验证。
        """
        config_defaults.retrieval_dedup_enabled = False
        patched["state"]["dense_order"] = ["v1", "v2"]
        service = _build_service({"v1": "同一段内容", "v2": "同一段内容"})

        result = service.search(KB_ID, "查询", top_k=5)

        assert len(result) == 2
        assert all("duplicate_count" not in item for item in result)


class TestDedupInteractsWithRerank:
    @pytest.fixture
    def recording_reranker(self, monkeypatch):
        """记录精排实际收到的候选，用于断言折叠发生在精排之前"""
        received: dict = {}

        class Recorder:
            def rerank(self, _query, candidates):
                received["candidates"] = list(candidates)
                return [(chunk_id, 1.0) for chunk_id, _ in candidates]

        monkeypatch.setattr("app.services.knowledge.get_reranker", lambda **_kwargs: Recorder())
        return received

    def test_dedupe_happens_before_rerank(self, patched, config_defaults, recording_reranker):
        """折叠必须先于精排：否则精排的候选预算被副本吃掉，且会对同一段反复推理"""
        patched["state"]["dense_order"] = ["v1", "v2", "v3"]
        service = _build_service({"v1": "同一段内容", "v2": "同一段内容", "v3": "另一段内容"})

        result = service.search(KB_ID, "查询", top_k=2, use_rerank=True, candidate_k=3)

        assert [chunk_id for chunk_id, _ in recording_reranker["candidates"]] == [
            "chunk-v1", "chunk-v3"
        ]
        # 折叠信息必须在精排之后仍然保留，否则界面无法解释结果条数
        assert result[0]["duplicate_count"] == 1
