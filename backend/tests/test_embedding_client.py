"""Embedding 客户端单元测试：覆盖本地 sentence-transformers provider 与配置驱动工厂。

说明：测试中对本地模型做 mock，不实际下载/加载权重，保证单测快速且可离线运行。
"""
import numpy as np
import pytest
from pydantic import SecretStr

from app.core.config import config
from app.core.vector_db import get_vector_size_for_model
from app.utils.embedding import (
    EmbeddingClient,
    get_embedding_client,
)


class _FakeSTModel:
    """模拟 sentence-transformers.SentenceTransformer，返回零向量。"""

    def __init__(self, dim: int):
        self._dim = dim

    def encode(self, texts, **kwargs):
        return np.zeros((len(texts), self._dim), dtype=np.float32)


@pytest.fixture
def fake_st_model(monkeypatch):
    """用假模型替换模型加载函数，维度按模型名推断。"""

    def _fake_load(model_name: str, device: str):
        return _FakeSTModel(get_vector_size_for_model(model_name))

    monkeypatch.setattr(
        "app.utils.embedding._get_sentence_transformer_model", _fake_load
    )


def test_factory_defaults_from_config(monkeypatch):
    """工厂缺省参数应回退到全局 config（修复此前 siliconflow 硬编码）。"""
    monkeypatch.setattr(config, "embedding_provider", "openai")
    monkeypatch.setattr(config, "embedding_model", "text-embedding-3-small")
    monkeypatch.setattr(config, "embedding_api_key", SecretStr("sk-test"))

    client = get_embedding_client()
    assert client.provider == "openai"
    assert client.model == "text-embedding-3-small"


def test_factory_explicit_override(monkeypatch):
    """显式传参应覆盖 config 默认值。"""
    monkeypatch.setattr(config, "embedding_provider", "openai")
    client = get_embedding_client(
        provider="sentence-transformers", model="BAAI/bge-base-zh-v1.5"
    )
    assert client.provider == "sentence-transformers"
    assert client.model == "BAAI/bge-base-zh-v1.5"


def test_sentence_transformers_provider_registered(fake_st_model):
    """本地 provider 应正确分发并返回与模型维度一致的向量。"""
    client = EmbeddingClient(
        provider="sentence-transformers", model="BAAI/bge-base-zh-v1.5"
    )
    texts = ["故障现象：CPU 使用率持续 99%", "磁盘 IO 出现长时间阻塞"]
    out = client.embed(texts)
    assert len(out) == len(texts)
    assert len(out[0]) == 768


def test_sentence_transformers_dim_large(fake_st_model):
    """不同本地模型应输出对应维度（large=1024）。"""
    client = EmbeddingClient(
        provider="sentence-transformers", model="BAAI/bge-large-zh-v1.5"
    )
    out = client.embed(["告警：内存耗尽"])
    assert len(out[0]) == 1024


def test_vector_size_mapping():
    """向量维度映射应覆盖新增的本地模型及 bge 家族兜底。"""
    assert get_vector_size_for_model("BAAI/bge-base-zh-v1.5") == 768
    assert get_vector_size_for_model("BAAI/bge-small-zh-v1.5") == 512
    assert get_vector_size_for_model("BAAI/bge-large-zh-v1.5") == 1024
    assert get_vector_size_for_model("BAAI/bge-m3") == 1024
    assert get_vector_size_for_model("shibing624/text2vec-base-chinese") == 768
    # 家族兜底
    assert get_vector_size_for_model("bge-base-anything") == 768
    assert get_vector_size_for_model("BAAI/bge-small-x") == 512
