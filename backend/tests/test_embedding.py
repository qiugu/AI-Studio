import pytest
import urllib3

from app.utils.embedding import EmbeddingClient, get_embedding_client


def test_embedding_client():
    client = get_embedding_client()
    vectors = client.embed(['hello world'])

    assert client is not None
    assert vectors is not None


def test_siliconflow_embedding_retries_after_incomplete_read(monkeypatch):
    class DummyResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"embedding": [0.1, 0.2, 0.3]}]}

    calls = []

    def fake_post(*args, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise urllib3.exceptions.IncompleteRead(10, 20)
        return DummyResponse()

    monkeypatch.setattr("requests.post", fake_post)

    client = EmbeddingClient(provider="siliconflow", model="BAAI/bge-large-zh-v1.5")
    vectors = client._embed_siliconflow(["hello world"])

    assert len(vectors) == 1
    assert vectors[0] == [0.1, 0.2, 0.3]
    assert len(calls) == 2
