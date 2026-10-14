from types import SimpleNamespace
from unittest.mock import MagicMock

from app.core.vector_db import NAMED_SPARSE_VECTOR
from app.models.knowledge_document import DocumentStatus
from app.services import knowledge_processor


def _run_task(monkeypatch, *, hybrid: bool):
    document = SimpleNamespace(
        id="doc-1",
        kb_id="kb-1",
        file_type="txt",
        status=DocumentStatus.PENDING,
        chunk_count=0,
        active_chunk_epoch=None,
        processed_at=None,
    )
    knowledge_base = SimpleNamespace(
        id="kb-1",
        embedding_model="BAAI/bge-base-zh-v1.5",
        active_collection=None,
        chunk_count=0,
    )

    document_query = MagicMock()
    document_query.filter.return_value.first.return_value = document
    knowledge_base_query = MagicMock()
    knowledge_base_query.filter.return_value.first.return_value = knowledge_base
    stale_query = MagicMock()
    stale_query.filter.return_value.delete.return_value = 0

    session = MagicMock()
    session.query.side_effect = [document_query, knowledge_base_query, stale_query]
    monkeypatch.setattr(knowledge_processor, "sessionLocal", lambda: session)

    chunk = SimpleNamespace(
        text="需要向量化的文本",
        index=0,
        kind="text",
        page=None,
        page_end=None,
        heading_path=None,
        heading_path_mixed=False,
    )
    monkeypatch.setattr(
        knowledge_processor.DocumentParser,
        "parse_segments",
        lambda *_args: [SimpleNamespace(text=chunk.text)],
    )

    class _Splitter:
        chunk_size = 448
        chunk_overlap = 64

        def split_segments(self, _segments):
            return [chunk]

    monkeypatch.setattr(knowledge_processor, "TextSplitter", _Splitter)
    monkeypatch.setattr(
        knowledge_processor,
        "get_embedding_client",
        lambda **_kwargs: SimpleNamespace(embed=lambda _texts: [[0.1, 0.2]]),
    )
    monkeypatch.setattr(knowledge_processor, "get_vector_size_for_model", lambda _model: 2)
    monkeypatch.setattr(knowledge_processor, "get_or_create_collection", lambda **_kwargs: "kb_kb-1")
    monkeypatch.setattr(knowledge_processor, "collection_name_for", lambda *_args: "kb_kb-1")
    monkeypatch.setattr(knowledge_processor.config, "retrieval_hybrid_enabled", hybrid)
    monkeypatch.setattr(knowledge_processor, "collection_layout", lambda _name: "missing")
    monkeypatch.setattr(
        knowledge_processor,
        "default_encoder",
        lambda: SimpleNamespace(document_vector=lambda _text: ([7], [1.5])),
    )

    qdrant = MagicMock()
    monkeypatch.setattr(knowledge_processor, "get_qdrant_client", lambda: qdrant)
    monkeypatch.setattr(
        knowledge_processor,
        "KnowledgeChunkRepository",
        lambda *_args, **_kwargs: SimpleNamespace(count_live_by_kb=lambda _kb_id: 1),
    )

    knowledge_processor.process_document_task.run("doc-1", "/tmp/doc.txt", "tenant-1")

    return qdrant.upsert.call_args.kwargs["points"][0], document


def test_legacy_collection_upsert_uses_unnamed_dense_vector(monkeypatch):
    """关闭混合检索时，PointStruct 必须匹配匿名稠密集合的写入契约。"""
    point, document = _run_task(monkeypatch, hybrid=False)

    assert point.vector == [0.1, 0.2]
    assert document.status == DocumentStatus.COMPLETED


def test_hybrid_collection_upsert_uses_named_vectors_without_nesting(monkeypatch):
    """混合集合的 dense/sparse 必须位于 PointStruct.vector 的第一层。"""
    point, document = _run_task(monkeypatch, hybrid=True)

    assert point.vector["dense"] == [0.1, 0.2]
    assert NAMED_SPARSE_VECTOR in point.vector
    assert document.status == DocumentStatus.COMPLETED
