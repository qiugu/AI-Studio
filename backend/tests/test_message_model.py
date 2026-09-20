"""messages 表 citations 列存在性守卫

防止迁移被漏执行（历史教训：曾因只交付迁移文件而未执行，启动即报
Unknown column 'messages.citations'）。列必须存在、为 JSON、可空。
"""
from __future__ import annotations

from sqlalchemy import JSON

from app.models.message import Message


def test_messages_has_citations_column():
    assert "citations" in Message.__table__.columns
    col = Message.__table__.columns["citations"]
    assert isinstance(col.type, JSON)
    assert col.nullable is True
