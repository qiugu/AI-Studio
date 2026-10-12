"""评测索引脚本单测（``scripts/index_rag_eval_corpus.py``）

脚本的关键契约是**落盘产物与集合布局**，而非内部实现细节，因此这里覆盖三层：

1. 纯函数：``point_id_for`` / ``build_chunks`` / ``build_sparse_encoder`` /
   ``build_point_vectors`` —— 分块口径、稀疏权重口径、向量字段形态；
2. 参数面：``--out-dir`` / ``--hybrid`` / ``--idf`` 是否真的被接线；
3. 端到端（全程使用替身，不触网、不连 Qdrant）：产物是否落在 ``--out-dir``、
   清单是否如实记录了布局与稀疏编码器参数。

第 3 点尤其重要：稠密与混合两次索引必须各写一个目录，否则后一次会覆盖前一次的
``chunks.jsonl``，「两次用的是不是同一份分块」就再也无法核对——而 Phase 5 的
对照结论完全依赖这一点成立。
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import List, Sequence

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
SCRIPT_PATH = BACKEND_DIR / "scripts" / "index_rag_eval_corpus.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location("index_rag_eval_corpus_test", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


indexer = _load_script_module()


def _long_text(marker: str, sentences: int = 120) -> str:
    return "".join(f"{marker}第{i}句内容用于撑开分块边界。" for i in range(sentences))


class TestPointId:
    def test_stable_and_unique(self):
        """point id 必须稳定（重复执行不产生重复索引）且区分段落与序号"""
        first = indexer.point_id_for("p1", 0)
        assert first == indexer.point_id_for("p1", 0)
        assert first != indexer.point_id_for("p1", 1)
        assert first != indexer.point_id_for("p2", 0)


class TestBuildChunks:
    def test_index_is_sequential_per_passage(self):
        corpus = [("p1", _long_text("甲")), ("p2", _long_text("乙"))]

        chunks = indexer.build_chunks(corpus, chunk_size=200, chunk_overlap=0)

        assert chunks
        # 每个段落的 chunk_index 从 0 连续递增（映射回段落的依据）
        for passage_id in ("p1", "p2"):
            indexes = [c["chunk_index"] for c in chunks if c["passage_id"] == passage_id]
            assert indexes == list(range(len(indexes)))
        assert all(c["point_id"] == indexer.point_id_for(c["passage_id"], c["chunk_index"])
                   for c in chunks)

    def test_overlap_is_now_effective(self):
        """``chunk_overlap`` 必须真实生效（D11 已修复）

        修复前重叠恒为 0，块数是「零重叠」的块数；修复后同样文本会多出块。
        该差异直接影响与历史基线的可比性，故在此钉死。
        """
        corpus = [("p1", _long_text("甲"))]

        without = indexer.build_chunks(corpus, chunk_size=200, chunk_overlap=0)
        with_overlap = indexer.build_chunks(corpus, chunk_size=200, chunk_overlap=60)

        assert len(with_overlap) > len(without)

    def test_matches_split_segments_output(self):
        """分块结果必须与线上同源的 ``split_segments`` 一致（同一调用路径）"""
        from app.utils.document import TextSegment, TextSplitter

        text = _long_text("甲")
        expected = [
            chunk.text
            for chunk in TextSplitter(chunk_size=200, chunk_overlap=20).split_segments(
                [TextSegment(text=text)]
            )
        ]

        chunks = indexer.build_chunks([("p1", text)], chunk_size=200, chunk_overlap=20)

        assert [c["text"] for c in chunks] == expected


class TestSparseEncoderSelection:
    def test_default_is_stateless(self):
        """默认（无 ``--idf``）必须是**无状态**编码器：IDF 恒为 1、可增量入库"""
        chunks = [{"text": _long_text("甲", 3)}]

        encoder = indexer.build_sparse_encoder(chunks, use_idf=False)

        assert encoder.is_stateless
        assert encoder.idf is None

    def test_idf_mode_fits_on_chunk_texts(self):
        """``--idf`` 在**分块文本**上拟合 df/avgdl，而非段落原文"""
        from app.utils.sparse import tokenize

        chunks = [
            {"text": "注意力机制 注意力机制 transformer"},
            {"text": "完全不同的另一段内容"},
        ]

        encoder = indexer.build_sparse_encoder(chunks, use_idf=True)

        assert not encoder.is_stateless
        assert encoder.idf is not None
        expected_avgdl = sum(len(tokenize(c["text"])) for c in chunks) / len(chunks)
        assert encoder.avgdl == pytest.approx(expected_avgdl)

    def test_sample_limit_restricts_fit_corpus(self):
        chunks = [{"text": "唯一词一次"}, {"text": _long_text("乙", 5)}]
        full = indexer.build_sparse_encoder(chunks, use_idf=True)
        sampled = indexer.build_sparse_encoder(chunks, use_idf=True, sample_limit=1)
        assert full.avgdl != sampled.avgdl


class TestPointVectorAssembly:
    def test_dense_only_returns_plain_lists(self):
        """无编码器时返回匿名稠密列表：与改造前的写入形态逐位一致"""
        dense = [[0.1, 0.2], [0.3, 0.4]]
        chunks = [{"text": "甲"}, {"text": "乙"}]

        vectors = indexer.build_point_vectors(dense, chunks, encoder=None)

        assert vectors == [[0.1, 0.2], [0.3, 0.4]]

    def test_hybrid_returns_named_vectors(self):
        """有编码器时返回命名向量字典，向量名由单点定义（避免写查不一致）"""
        from app.core.vector_db import NAMED_DENSE_VECTOR, NAMED_SPARSE_VECTOR

        dense = [[0.1, 0.2], [0.3, 0.4]]
        chunks = [{"text": "注意力机制"}, {"text": "另一段"}]
        encoder = indexer.build_sparse_encoder(chunks, use_idf=False)

        vectors = indexer.build_point_vectors(dense, chunks, encoder)

        assert len(vectors) == 2
        for vector, expected_dense in zip(vectors, dense):
            assert isinstance(vector, dict)
            assert vector[NAMED_DENSE_VECTOR] == expected_dense
            assert NAMED_SPARSE_VECTOR in vector  # SparseVector(indices/values)
            assert vector[NAMED_SPARSE_VECTOR].indices


class TestParserWiring:
    def test_help_renders_without_format_errors(self):
        """``--help`` 必须能正常渲染

        ``ArgumentDefaultsHelpFormatter`` 会对帮助文本做 ``%``-插值，help 字符串里
        一个**字面** ``%``（例如写「增益约高 30%」）就会让 ``format_help()`` 抛
        ``ValueError``，把 `--help` 变成一段栈回溯。曾真实发生，故在此钉死。
        """
        text = indexer.build_parser().format_help()

        assert "--out-dir" in text
        assert "--hybrid" in text
        assert "--idf" in text

    def test_new_flags_exist_with_conservative_defaults(self):
        """默认必须保持「与改造前一致」：非混合、无 IDF、产物落回 data-dir"""
        args = indexer.build_parser().parse_args([])

        assert args.hybrid is False
        assert args.idf is False
        assert args.out_dir is None
        assert args.idf_sample_limit is None

    def test_flags_can_be_enabled(self):
        args = indexer.build_parser().parse_args(
            ["--hybrid", "--idf", "--out-dir", "/tmp/x", "--idf-sample-limit", "100"]
        )

        assert args.hybrid is True
        assert args.idf is True
        assert args.out_dir == "/tmp/x"
        assert args.idf_sample_limit == 100


class _FakeEmbeddingClient:
    """替身嵌入客户端：固定维度，不加载任何模型"""

    DIM = 4

    def embed(self, texts: Sequence[str]) -> List[List[float]]:
        return [[0.0] * self.DIM for _ in texts]


@pytest.fixture
def eval_data_dir(tmp_path):
    """最小可用的评测数据目录（语料 + 金标）"""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "corpus.jsonl").write_text(
        "\n".join(
            json.dumps({"id": f"p{i}", "text": _long_text(f"甲{i}", 40)}, ensure_ascii=False)
            for i in range(1, 4)
        )
        + "\n",
        encoding="utf-8",
    )
    (data_dir / "golden.jsonl").write_text(
        json.dumps(
            {"query_id": "q1", "query": "甲1", "relevant": [{"id": "p1"}]},
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return data_dir


@pytest.fixture
def stubbed_io(monkeypatch):
    """替换掉一切外部交互（模型 / Qdrant / 写入），只保留脚本自身逻辑"""
    calls = {"upserts": [], "collections": []}

    monkeypatch.setattr(indexer, "get_embedding_client", lambda model=None: _FakeEmbeddingClient())

    def fake_get_or_create_collection(kb_id, vector_size=1024, *, hybrid=False, active=None):
        calls["collections"].append({"kb_id": kb_id, "hybrid": hybrid, "vector_size": vector_size})
        return indexer.collection_name_for(kb_id, active)

    monkeypatch.setattr(indexer, "get_or_create_collection", fake_get_or_create_collection)
    monkeypatch.setattr(indexer, "upsert_points",
                        lambda collection, chunks, vectors: calls["upserts"].append(
                            {"collection": collection, "n": len(chunks),
                             "hybrid": isinstance(vectors[0], dict) if vectors else False}))
    return calls


class TestMainArtifacts:
    def test_dense_run_writes_artifacts_into_out_dir(self, eval_data_dir, tmp_path, stubbed_io):
        """产物必须落在 ``--out-dir``，而不是无脑写回 ``--data-dir``"""
        out_dir = tmp_path / "dense_out"

        code = indexer.main([
            "--data-dir", str(eval_data_dir),
            "--out-dir", str(out_dir),
            "--kb-slug", "rageval_dense_test",
        ])

        assert code == 0
        assert (out_dir / "chunks.jsonl").exists()
        assert (out_dir / "index_manifest.json").exists()
        manifest = json.loads((out_dir / "index_manifest.json").read_text(encoding="utf-8"))
        assert manifest["layout"] == "legacy_dense"
        assert manifest["sparse_encoder"] is None
        assert manifest["out_dir"] == str(out_dir)
        assert manifest["collection"] == "kb_rageval_dense_test"
        # 未请求混合布局时不得留下稀疏编码器产物
        assert not (out_dir / "sparse_encoder.json").exists()
        # 且集合必须按非混合布局创建
        assert stubbed_io["collections"][0]["hybrid"] is False

    def test_hybrid_run_creates_hybrid_collection_and_named_vectors(
        self, eval_data_dir, tmp_path, stubbed_io
    ):
        out_dir = tmp_path / "hybrid_out"

        indexer.main([
            "--data-dir", str(eval_data_dir),
            "--out-dir", str(out_dir),
            "--kb-slug", "rageval_hybrid_test",
            "--hybrid",
        ])

        assert stubbed_io["collections"][0]["hybrid"] is True
        assert stubbed_io["upserts"][0]["hybrid"] is True
        manifest = json.loads((out_dir / "index_manifest.json").read_text(encoding="utf-8"))
        assert manifest["layout"] == "hybrid"
        assert manifest["sparse_encoder"]["mode"] == "stateless"

    def test_idf_mode_persists_encoder_stats(self, eval_data_dir, tmp_path, stubbed_io):
        """``--idf`` 必须把拟合出的 k1/b/avgdl/idf 落盘，否则事后无法复现"""
        out_dir = tmp_path / "hybrid_idf_out"

        indexer.main([
            "--data-dir", str(eval_data_dir),
            "--out-dir", str(out_dir),
            "--kb-slug", "rageval_hybrid_idf_test",
            "--hybrid",
            "--idf",
        ])

        encoder_path = out_dir / "sparse_encoder.json"
        assert encoder_path.exists()
        payload = json.loads(encoder_path.read_text(encoding="utf-8"))
        assert payload["idf"]
        assert payload["avgdl"] > 0
        manifest = json.loads((out_dir / "index_manifest.json").read_text(encoding="utf-8"))
        assert manifest["sparse_encoder"]["mode"] == "idf"
        assert manifest["sparse_encoder"]["idf_terms"] == len(payload["idf"])

    def test_two_runs_do_not_overwrite_each_other(self, eval_data_dir, tmp_path, stubbed_io):
        """稠密与混合两次索引的 ``chunks.jsonl`` 必须能同时留存

        这是 Phase 5 对照结论成立的前提：两次的分块集合必须一致，若后一次覆盖
        前一次，事后就无从核对。
        """
        dense_out = tmp_path / "run_dense"
        hybrid_out = tmp_path / "run_hybrid"

        indexer.main(["--data-dir", str(eval_data_dir), "--out-dir", str(dense_out),
                      "--kb-slug", "rageval_dense_test"])
        indexer.main(["--data-dir", str(eval_data_dir), "--out-dir", str(hybrid_out),
                      "--kb-slug", "rageval_hybrid_test", "--hybrid"])

        dense_chunks = (dense_out / "chunks.jsonl").read_text(encoding="utf-8")
        hybrid_chunks = (hybrid_out / "chunks.jsonl").read_text(encoding="utf-8")
        # 同一语料 + 同一分块参数 → 逐字符相同（对照的可比性证据）
        assert dense_chunks == hybrid_chunks
        assert (dense_out / "index_manifest.json").exists()
        assert (hybrid_out / "index_manifest.json").exists()

    def test_missing_corpus_reports_actionable_error(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        with pytest.raises(SystemExit) as excinfo:
            indexer.main(["--data-dir", str(empty)])
        assert "缺少语料文件" in str(excinfo.value)


class TestCutReport:
    def test_detects_split_passages_and_ratio(self, tmp_path):
        golden = tmp_path / "golden.jsonl"
        golden.write_text(
            "\n".join([
                json.dumps({"query_id": "q1", "query": "x", "relevant": [{"id": "p1"}, {"id": "p2"}]}),
                json.dumps({"query_id": "q2", "query": "y", "relevant": [{"id": "p3"}]}),
            ])
            + "\n",
            encoding="utf-8",
        )
        chunks = [
            {"passage_id": "p1", "chunk_index": 0, "text": "a"},
            {"passage_id": "p1", "chunk_index": 1, "text": "b"},
            {"passage_id": "p2", "chunk_index": 0, "text": "c"},
            {"passage_id": "p3", "chunk_index": 0, "text": "d"},
        ]

        report = indexer.build_cut_report(
            golden, chunks, {"p1": 10, "p2": 10, "p3": 10}
        )

        assert report["n_chunks"] == 4
        assert report["passages_with_multiple_chunks"] == 1
        assert report["n_relevant_split"] == 1
        assert report["n_relevant_total"] == 3
        assert report["split_relevant_ratio"] == pytest.approx(round(1 / 3, 4))
        assert report["n_queries_affected"] == 1
