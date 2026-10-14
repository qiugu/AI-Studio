"""数据集模块单测：schema 校验必须拒绝「会让指标失真」的标注

核心立场：宁可拒绝加载，也不接受一份「能跑通但标注有问题」的数据集。
被静默接受的坏数据会变成看起来很好的指标，比报错危险得多。
"""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.rag_eval.dataset import (
    CorpusEntry,
    GoldenQuery,
    GoldenSet,
    dump_jsonl,
    load_jsonl,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "rag_eval"


class TestGoldenQueryValidation:
    def test_valid_query_parses(self):
        query = GoldenQuery.model_validate(
            {
                "query_id": "q1",
                "query": "分块大小是多少",
                "query_type": "fact",
                "relevant": [{"id": "c1", "grade": 1, "passage_id": "p1"}],
            }
        )
        assert query.relevant_ids == ["c1"]
        assert query.gains == {"c1": 1}
        assert query.passage_ids == ["p1"]

    def test_empty_relevant_is_rejected(self):
        """无标准答案的查询必须被拒绝：否则指标无定义，且无法区分「标注漏了」与「检索失败」"""
        with pytest.raises(ValidationError):
            GoldenQuery.model_validate({"query_id": "q1", "query": "x", "relevant": []})

    def test_blank_query_is_rejected(self):
        with pytest.raises(ValidationError):
            GoldenQuery.model_validate(
                {"query_id": "q1", "query": "   ", "relevant": [{"id": "c1"}]}
            )

    def test_blank_query_id_is_rejected(self):
        with pytest.raises(ValidationError):
            GoldenQuery.model_validate({"query_id": "", "query": "x", "relevant": [{"id": "c1"}]})

    @pytest.mark.parametrize("bad_grade", [0, -1])
    def test_non_positive_grade_is_rejected(self, bad_grade):
        """负相关度/零相关度出现在 relevant 列表里属于标注错误，直接拒绝"""
        with pytest.raises(ValidationError):
            GoldenQuery.model_validate(
                {"query_id": "q1", "query": "x", "relevant": [{"id": "c1", "grade": bad_grade}]}
            )

    def test_duplicate_relevant_ids_rejected(self):
        """重复标注会让 Recall 分母虚增，必须拒绝"""
        with pytest.raises(ValidationError, match="duplicate ids"):
            GoldenQuery.model_validate(
                {
                    "query_id": "q1",
                    "query": "x",
                    "relevant": [{"id": "c1"}, {"id": "c1"}],
                }
            )

    def test_unknown_field_rejected(self):
        """多余字段视为拼写错误，不允许静默忽略"""
        with pytest.raises(ValidationError):
            GoldenQuery.model_validate(
                {
                    "query_id": "q1",
                    "query": "x",
                    "relevant": [{"id": "c1"}],
                    "relvant_typo": 1,
                }
            )


class TestGoldenSet:
    def test_duplicate_query_id_across_set_rejected(self):
        with pytest.raises(ValidationError, match="duplicate query_id"):
            GoldenSet(
                queries=[
                    {"query_id": "q1", "query": "a", "relevant": [{"id": "c1"}]},
                    {"query_id": "q1", "query": "b", "relevant": [{"id": "c2"}]},
                ]
            )

    def test_groups_and_unique_pool(self):
        golden = GoldenSet(
            queries=[
                {"query_id": "q1", "query": "a", "query_type": "fact", "relevant": [{"id": "c1"}]},
                {"query_id": "q2", "query": "b", "relevant": [{"id": "c1"}, {"id": "c2"}]},
            ]
        )
        assert golden.groups == {"q1": "fact", "q2": "unknown"}
        assert sorted(golden.relevant_id_pool) == ["c1", "c2"]
        assert len(golden) == 2

    def test_stats_hand_computed(self):
        golden = GoldenSet(
            queries=[
                {"query_id": "q1", "query": "a", "query_type": "fact", "relevant": [{"id": "c1"}]},
                {"query_id": "q2", "query": "b", "query_type": "fact", "relevant": [{"id": "c1"}]},
                {"query_id": "q3", "query": "c", "query_type": "multi", "relevant": [{"id": "c2"}]},
            ]
        )
        stats = golden.stats()
        assert stats["n_queries"] == 3
        assert stats["query_type_distribution"] == {"fact": 2, "multi": 1}
        assert stats["n_relevant_total"] == 3
        assert stats["n_unique_relevant_units"] == 2
        assert stats["n_relevant_per_query"] == {"min": 1, "max": 1, "mean": 1.0}


class TestJsonlIO:
    def test_load_jsonl_reports_line_number_on_bad_json(self, tmp_path):
        """行号必须报出来：否则定位坏标签要逐行肉眼比对"""
        path = tmp_path / "bad.jsonl"
        path.write_text('{"a": 1}\n\n{bad json}\n', encoding="utf-8")
        with pytest.raises(ValueError, match=r":3 invalid JSON"):
            load_jsonl(path)

    def test_load_jsonl_rejects_non_object_line(self, tmp_path):
        path = tmp_path / "list.jsonl"
        path.write_text("[1, 2, 3]\n", encoding="utf-8")
        with pytest.raises(ValueError, match="expected a JSON object"):
            load_jsonl(path)

    def test_load_jsonl_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_jsonl(tmp_path / "nope.jsonl")

    def test_dump_and_load_round_trip_preserves_chinese(self, tmp_path):
        entries = [CorpusEntry(id="c1", text="中文内容不转义")]
        path = dump_jsonl(entries, tmp_path / "corpus.jsonl")
        raw = path.read_text(encoding="utf-8")
        assert "中文内容不转义" in raw  # ensure_ascii=False
        assert load_jsonl(path) == [{"id": "c1", "text": "中文内容不转义"}]

    def test_golden_set_load_reads_sibling_manifest(self, tmp_path):
        dump_jsonl(
            [{"query_id": "q1", "query": "a", "relevant": [{"id": "c1"}]}],
            tmp_path / "golden.jsonl",
        )
        (tmp_path / "manifest.json").write_text(
            json.dumps({"seed": 42, "corpus_size": 20000}, ensure_ascii=False),
            encoding="utf-8",
        )
        golden = GoldenSet.load(tmp_path / "golden.jsonl")
        assert golden.manifest == {"seed": 42, "corpus_size": 20000}


class TestFixtureDataset:
    """内置夹具数据集必须始终可加载——它是离线冒烟与 CI 的基础"""

    def test_fixture_corpus_and_golden_load(self):
        golden = GoldenSet.load(FIXTURE_DIR / "golden.jsonl")
        assert len(golden) == 6
        assert golden.stats()["n_queries"] == 6

        corpus = {entry["id"] for entry in load_jsonl(FIXTURE_DIR / "corpus.jsonl")}
        missing = [doc_id for doc_id in golden.relevant_id_pool if doc_id not in corpus]
        assert missing == [], f"夹具金标准引用了不存在的语料单元：{missing}"
