from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.models.knowledge_document import DocumentStatus
from app.services import knowledge_processor


def test_document_processing_records_failure_and_reraises(monkeypatch):
    document = SimpleNamespace(
        status=DocumentStatus.PROCESSING,
        error_message=None,
    )
    session = MagicMock()
    initial_query = MagicMock()
    initial_query.filter.return_value.first.side_effect = RuntimeError(
        "database unavailable"
    )
    failure_query = MagicMock()
    failure_query.filter.return_value.first.return_value = document
    session.query.side_effect = [initial_query, failure_query]
    monkeypatch.setattr(knowledge_processor, "sessionLocal", lambda: session)

    with pytest.raises(RuntimeError, match="database unavailable"):
        knowledge_processor.process_document_task.run(
            "doc-1", "/tmp/doc.txt", "tenant-1"
        )

    assert document.status == DocumentStatus.FAILED
    assert document.error_message == "database unavailable"
    session.close.assert_called_once()
