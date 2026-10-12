"""Qdrant 集合创建单元测试：覆盖新建、并发 409 容错、维度不一致校验。"""
import types

import pytest
from qdrant_client.http.exceptions import UnexpectedResponse

from app.core.vector_db import get_or_create_collection


class FakeQdrant:
    """内存假 Qdrant 客户端，复现并发建表的 409 Conflict。"""

    def __init__(self):
        self.collections = {}  # name -> vector_size
        self.create_calls = 0

    def get_collections(self):
        return types.SimpleNamespace(
            collections=[types.SimpleNamespace(name=n) for n in self.collections]
        )

    def create_collection(self, collection_name, vectors_config, hnsw_config=None):
        self.create_calls += 1
        if collection_name in self.collections:
            raise UnexpectedResponse(409, "Conflict", b"", {})
        self.collections[collection_name] = vectors_config.size

    def get_collection(self, collection_name):
        size = self.collections[collection_name]
        return types.SimpleNamespace(
            config=types.SimpleNamespace(
                params=types.SimpleNamespace(vectors=types.SimpleNamespace(size=size))
            )
        )


@pytest.fixture
def fake_qdrant(monkeypatch):
    fq = FakeQdrant()
    monkeypatch.setattr("app.core.vector_db.get_qdrant_client", lambda: fq)
    return fq


def test_create_new_collection(fake_qdrant):
    name = get_or_create_collection("kb_new", vector_size=768)
    assert name == "kb_kb_new"
    assert "kb_kb_new" in fake_qdrant.collections
    assert fake_qdrant.collections["kb_kb_new"] == 768


def test_concurrent_create_tolerates_409(fake_qdrant, monkeypatch):
    # 模拟并发竞态：两个任务都先读到“集合不存在”，再同时尝试建表
    monkeypatch.setattr(
        fake_qdrant,
        "get_collections",
        lambda: types.SimpleNamespace(collections=[]),
    )
    get_or_create_collection("kb_x", vector_size=768)  # 首次建表
    name = get_or_create_collection("kb_x", vector_size=768)  # 并发建表，应被 409 容错
    assert name == "kb_kb_x"
    assert fake_qdrant.create_calls == 2  # 两次尝试，第二次被忽略


def test_existing_collection_size_mismatch_raises(fake_qdrant):
    get_or_create_collection("kb_m", vector_size=768)
    with pytest.raises(ValueError):
        get_or_create_collection("kb_m", vector_size=1024)
