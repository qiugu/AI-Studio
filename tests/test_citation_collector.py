"""CitationCollector 纯逻辑测试（不连数据库、不连 LLM）

覆盖编号分配、跨调用延续、chunk_id 去重、大内容截断、字段完整性。
"""
from __future__ import annotations

from app.utils.citation import CitationCollector


def _result(cid: str, **kw) -> dict:
    base = {
        "id": cid,
        "content": f"content-{cid}",
        "doc_id": "d1",
        "doc_name": "手册.pdf",
        "chunk_index": 0,
        "source_page": 1,
        "source_page_end": 2,
        "heading_path": None,
        "heading_path_mixed": False,
        "score": 0.9,
        "llm_content": f"[{cid}] content-{cid}",
        "context_header": "[《手册.pdf》 | p.1–2]",
        "context_expanded": False,
    }
    base.update(kw)
    return base


class TestMarkerAssignment:
    def test_markers_start_at_one_and_increase(self):
        c = CitationCollector()
        m = c.register([_result("a"), _result("b"), _result("c")], tool_name="kb", query="q")
        assert m == [1, 2, 3]
        assert [x["marker"] for x in c.snapshot()] == [1, 2, 3]

    def test_across_multiple_register_calls_continues(self):
        c = CitationCollector()
        m1 = c.register([_result("a"), _result("b")], tool_name="kb", query="q")
        m2 = c.register([_result("c")], tool_name="kb", query="q2")
        assert m1 == [1, 2]
        assert m2 == [3]
        assert len(c) == 3

    def test_same_chunk_reuses_marker(self):
        c = CitationCollector()
        m1 = c.register([_result("a"), _result("b")], tool_name="kb", query="q")
        # 第二次召回含相同的 a（去重）与新的 d
        m2 = c.register([_result("a"), _result("d")], tool_name="kb", query="q2")
        assert m1 == [1, 2]
        # a 沿用首次编号 1；d 为新编号 3
        assert m2 == [1, 3]
        assert len(c) == 3

    def test_no_results_registers_nothing(self):
        c = CitationCollector()
        m = c.register([], tool_name="kb", query="q")
        assert m == []
        assert len(c) == 0


class TestContentSnapshot:
    def test_large_content_truncated_when_flag_set(self):
        c = CitationCollector()
        big = "x" * 2000
        c.register([_result("a", content=big)], tool_name="kb", query="q", max_content_chars=1200)
        snap = c.snapshot()
        assert snap[0]["content_truncated"] is True
        assert len(snap[0]["content"]) == 1200

    def test_no_truncation_when_flag_none(self):
        c = CitationCollector()
        big = "x" * 2000
        c.register([_result("a", content=big)], tool_name="kb", query="q", max_content_chars=None)
        snap = c.snapshot()
        assert snap[0]["content_truncated"] is False
        assert len(snap[0]["content"]) == 2000


class TestFields:
    def test_citation_carries_source_metadata(self):
        c = CitationCollector()
        c.register(
            [
                _result(
                    "a",
                    doc_name="运维手册.pdf",
                    source_page=37,
                    source_page_end=38,
                    heading_path="§3.2",
                )
            ],
            tool_name="kb1",
            query="超时多少",
            kb_id="kb-uuid",
        )
        snap = c.snapshot()[0]
        assert snap["doc_name"] == "运维手册.pdf"
        assert snap["source_page"] == 37
        assert snap["source_page_end"] == 38
        assert snap["heading_path"] == "§3.2"
        assert snap["kb_id"] == "kb-uuid"
        assert snap["tool_name"] == "kb1"
        assert snap["query"] == "超时多少"
        # 装配层三键原样保留
        assert "llm_content" in snap and "context_header" in snap and "context_expanded" in snap
