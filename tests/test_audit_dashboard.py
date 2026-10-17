"""Dashboard tool observability aggregation tests."""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.audit import AuditService


def test_dashboard_aggregates_persisted_tool_observations():
    query = MagicMock()
    query.filter.return_value = query
    query.order_by.return_value = query
    query.all.return_value = [
        SimpleNamespace(
            created_at=datetime(2026, 10, 16, 10, 2),
            tool_calls=[
                {"call_id": "run-2", "tool": "knowledge-kb-1", "status": "success"},
                {"call_id": "run-3", "tool": "crm-search", "status": "error"},
            ],
        ),
        SimpleNamespace(
            created_at=datetime(2026, 10, 15, 9, 0),
            tool_calls=[
                {"call_id": "run-1", "tool": "knowledge-kb-1", "status": "success"},
            ],
        ),
    ]
    db = MagicMock()
    db.query.return_value = query

    result = AuditService(db, "tenant-1")._tool_observability(
        datetime(2026, 10, 1), datetime(2026, 10, 16, 23, 59)
    )

    assert result["tool_calls_30d"] == 3
    assert result["tool_success_rate_30d"] == 66.7
    assert result["top_tools"][0] == {
        "key": "knowledge-kb-1",
        "call_count": 2,
        "success_count": 2,
        "error_count": 0,
    }
    assert result["recent_tool_calls"][0]["tool"] == "knowledge-kb-1"
