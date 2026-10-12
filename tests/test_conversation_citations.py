"""add_message 透传 citations 字段（不连真实数据库）

用内存构造 ORM 对象验证 ``citations`` 参数从 Service 层一路落到 Repository 创建，
无引用时落库为 None（而非空数组）。
"""
from __future__ import annotations

from unittest.mock import MagicMock

from app.models.message import Message
from app.repositories.conversation import MessageRepository
from app.services.conversation import ConversationService


def _make_repo():
    captured: dict = {}

    def fake_create(**kwargs):
        instance = Message(**kwargs)
        captured["instance"] = instance
        return instance

    db = MagicMock()
    db.add = MagicMock()
    db.flush = MagicMock()
    repo = MessageRepository(db=db, tenant_id="t")
    repo.create = fake_create  # 内存构造 ORM 对象，避免真实 DB
    return repo, captured


def _make_service(repo) -> ConversationService:
    svc = ConversationService(db=MagicMock(), tenant_id="t")
    svc.msg_repo = repo
    svc.conv_repo = MagicMock()  # get_by_id 返回真值，走到 update 不报错
    return svc


class TestAddMessageCitations:
    def test_citations_persisted(self):
        repo, captured = _make_repo()
        svc = _make_service(repo)
        sample = [{"marker": 1, "chunk_id": "c1", "doc_name": "m.pdf", "content": "甲"}]
        svc.add_message(conversation_id="conv", role="assistant", content="答", citations=sample)
        assert captured["instance"].citations == sample

    def test_no_citations_stored_as_none(self):
        repo, captured = _make_repo()
        svc = _make_service(repo)
        svc.add_message(conversation_id="conv", role="assistant", content="答")
        assert captured["instance"].citations is None
