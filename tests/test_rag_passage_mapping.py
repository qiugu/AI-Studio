"""索引清单与「分块 → 段落」折叠的单测

这里验证的是评测口径的**正确性**：基准的标准答案是段落，索引单元是分块，
折叠逻辑一旦出错，指标就会系统性偏斜（例如同一段落的多个分块挤占 top-k，
或 Recall 的分母随分块参数变化），而报告上只会表现为一个看似正常的数字。
"""

from __future__ import annotations

import json

import pytest

from app.rag_eval.index_manifest import IndexManifest, load_index_manifest
from app.rag_eval.retrievers import PassageMappedRetriever, RetrievalResult


class StubRetriever:
    """返回预设分块级结果，并记录被索取的 top_k"""

    name = "stub"

    def __init__(self, ids, scores=None, candidate_ids=None):
        self._ids = list(ids)
        self._scores = list(scores) if scores else [1.0 - i * 0.01 for i in range(len(ids))]
        self._candidate_ids = list(candidate_ids) if candidate_ids else None
        self.requested: list[int] = []

    def retrieve(self, _query: str, top_k: int) -> RetrievalResult:
        self.requested.append(top_k)
        return RetrievalResult(
            ids=self._ids[:top_k],
            scores=self._scores[:top_k],
            candidate_ids=self._candidate_ids,
            candidate_scores=[1.0] * len(self._candidate_ids) if self._candidate_ids else None,
        )


def _manifest(chunks) -> IndexManifest:
    """chunks: [(point_id, passage_id, chunk_index, text)]"""
    from app.rag_eval.index_manifest import ChunkRecord

    return IndexManifest(
        collection="kb_test",
        chunks=[ChunkRecord(*item) for item in chunks],
        params={"collection": "kb_test", "n_chunks": len(chunks)},
    )


class TestIndexManifest:
    def test_id_map_and_chunk_text(self):
        manifest = _manifest([
            ("p1", "doc-a", 0, "甲"),
            ("p2", "doc-a", 1, "乙"),
            ("p3", "doc-b", 0, "丙"),
        ])

        assert manifest.id_map == {"p1": "doc-a", "p2": "doc-a", "p3": "doc-b"}
        assert manifest.chunk_text("p2") == "乙"
        assert manifest.chunk_text("missing") is None

    def test_chunks_per_passage_and_counts(self):
        manifest = _manifest([
            ("p1", "doc-a", 0, "甲"),
            ("p2", "doc-a", 1, "乙"),
            ("p3", "doc-b", 0, "丙"),
        ])

        assert manifest.chunks_per_passage() == {"doc-a": 2, "doc-b": 1}
        assert manifest.n_passages == 2
        assert manifest.n_chunks == 3
        assert manifest.summary()["n_passages"] == 2

    def test_summary_merges_params(self):
        manifest = _manifest([("p1", "doc-a", 0, "甲")])
        summary = manifest.summary()
        assert summary["collection"] == "kb_test"
        assert summary["n_chunks"] == 1


class TestLoadIndexManifest:
    def _write(self, tmp_path, chunks, manifest):
        (tmp_path / "chunks.jsonl").write_text(
            "\n".join(json.dumps(item, ensure_ascii=False) for item in chunks) + "\n",
            encoding="utf-8",
        )
        (tmp_path / "index_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
        )

    def test_loads_chunks_and_params(self, tmp_path):
        self._write(
            tmp_path,
            [
                {"point_id": "p1", "passage_id": "doc-a", "chunk_index": 0, "text": "甲"},
                {"point_id": "p2", "passage_id": "doc-a", "chunk_index": 1, "text": "乙"},
            ],
            {"collection": "kb_test", "vector_dim": 768},
        )
        manifest = load_index_manifest(tmp_path)

        assert manifest.collection == "kb_test"
        assert manifest.n_chunks == 2
        assert manifest.params["vector_dim"] == 768

    def test_missing_chunks_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="chunks.jsonl"):
            load_index_manifest(tmp_path)

    def test_missing_collection_raises(self, tmp_path):
        self._write(
            tmp_path,
            [{"point_id": "p1", "passage_id": "doc-a", "chunk_index": 0, "text": "甲"}],
            {"vector_dim": 768},
        )
        with pytest.raises(ValueError, match="collection"):
            load_index_manifest(tmp_path)


class TestPassageMappedRetriever:
    def test_folds_multiple_chunks_into_one_passage(self):
        """同一段落的多个分块必须折叠为一条，否则会挤占其他段落的 top-k 名额"""
        base = StubRetriever(["p1", "p2", "p3"])
        retriever = PassageMappedRetriever(
            base, {"p1": "doc-a", "p2": "doc-a", "p3": "doc-b"}
        )
        result = retriever.retrieve("q", top_k=3)

        assert result.ids == ["doc-a", "doc-b"]

    def test_keeps_first_occurrence_rank(self):
        """折叠后保留该段落最好分块的排名——语义是「段落排在第几」"""
        base = StubRetriever(["p1", "p2", "p3", "p4"])
        retriever = PassageMappedRetriever(
            base, {"p1": "doc-a", "p2": "doc-b", "p3": "doc-a", "p4": "doc-c"}
        )
        result = retriever.retrieve("q", top_k=3)

        assert result.ids == ["doc-a", "doc-b", "doc-c"]

    def test_score_comes_from_best_chunk(self):
        base = StubRetriever(["p1", "p2"], scores=[0.9, 0.4])
        retriever = PassageMappedRetriever(base, {"p1": "doc-a", "p2": "doc-a"})
        result = retriever.retrieve("q", top_k=1)

        assert result.scores == [0.9]

    def test_requests_oversampled_candidates(self):
        """去重必然缩短列表，必须向底层索取更多结果，否则填不满 top_k"""
        base = StubRetriever([f"p{i}" for i in range(50)])
        retriever = PassageMappedRetriever(base, {}, oversample=5)
        retriever.retrieve("q", top_k=10)

        assert base.requested == [50]

    def test_max_fetch_caps_oversampling(self):
        base = StubRetriever([f"p{i}" for i in range(50)])
        retriever = PassageMappedRetriever(base, {}, oversample=100, max_fetch=30)
        retriever.retrieve("q", top_k=10)

        assert base.requested == [30]

    def test_truncates_to_top_k_after_folding(self):
        base = StubRetriever([f"p{i}" for i in range(30)])
        retriever = PassageMappedRetriever(base, {f"p{i}": f"doc-{i}" for i in range(30)})
        result = retriever.retrieve("q", top_k=4)

        assert len(result.ids) == 4

    def test_candidate_ids_are_folded_too(self):
        """候选集同样要折叠，否则 candidate_recall 会在分块粒度上计算，与其它指标不可比"""
        base = StubRetriever(
            ["p1"], candidate_ids=["p1", "p2", "p3"], 
        )
        retriever = PassageMappedRetriever(base, {"p1": "doc-a", "p2": "doc-a", "p3": "doc-b"})
        result = retriever.retrieve("q", top_k=1)

        assert result.candidate_ids == ["doc-a", "doc-b"]

    def test_unmapped_ids_are_retained_and_counted(self):
        """索引与清单漂移时不能静默丢弃：保留原 id 让问题以 Recall 偏低显式暴露"""
        base = StubRetriever(["p1", "ghost"])
        retriever = PassageMappedRetriever(base, {"p1": "doc-a"})
        result = retriever.retrieve("q", top_k=2)

        assert result.ids == ["doc-a", "ghost"]
        assert retriever.unmapped_count == 1

    def test_latency_is_passed_through(self):
        base = StubRetriever(["p1", "p2"], scores=[0.9, 0.4])
        retriever = PassageMappedRetriever(base, {"p1": "doc-a", "p2": "doc-a"})
        result = retriever.retrieve("q", top_k=1)

        assert result.retrieve_latency_ms == 0.0
        assert result.rerank_latency_ms is None

    @pytest.mark.parametrize(("oversample", "max_fetch"), [(0, 5), (5, 0), (-1, 5)])
    def test_invalid_configuration_rejected(self, oversample, max_fetch):
        with pytest.raises(ValueError):
            PassageMappedRetriever(StubRetriever([]), {}, oversample=oversample, max_fetch=max_fetch)

    def test_empty_base_result(self):
        retriever = PassageMappedRetriever(StubRetriever([]), {})
        result = retriever.retrieve("q", top_k=5)

        assert result.ids == []
        assert result.candidate_ids is None


class TestChainedWithRerank:
    """精排作用在分块上、折叠发生在最后——顺序颠倒会改变被评测的对象"""

    def test_rerank_then_fold(self):
        from app.rag_eval.retrievers import RerankedRetriever

        # 稠密顺序为 p1(doc-a) p2(doc-b) p3(doc-a)；精排把 p3 提到最前
        base = StubRetriever(["p1", "p2", "p3"])
        chunk_text = {"p1": "一", "p2": "二", "p3": "三"}
        reranked = RerankedRetriever(
            base=base,
            rerank_fn=lambda _q, candidates: [
                (doc_id, {"p3": 9.0, "p1": 5.0, "p2": 1.0}[doc_id]) for doc_id, _ in candidates
            ],
            text_lookup=chunk_text.get,
            candidate_k=10,
        )
        mapped = PassageMappedRetriever(
            reranked, {"p1": "doc-a", "p2": "doc-b", "p3": "doc-a"}
        )
        result = mapped.retrieve("q", top_k=2)

        # p3 与 p1 同属 doc-a，折叠后占首位；doc-b 次之
        assert result.ids == ["doc-a", "doc-b"]
        assert result.rerank_latency_ms is not None
