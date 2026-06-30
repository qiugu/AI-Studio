import pytest

from app.core.vector_db import get_vector_size_for_model


def test_get_vector_size_for_model_known_models():
    assert get_vector_size_for_model("text-embedding-3-small") == 1536
    assert get_vector_size_for_model("text-embedding-3-large") == 3072
    assert get_vector_size_for_model("text-embedding-ada-002") == 1536
    assert get_vector_size_for_model("text-embedding-3-small-zh") == 1536
    assert get_vector_size_for_model("text-embedding-3-large-zh") == 3072


def test_get_vector_size_for_model_bge_variants():
    assert get_vector_size_for_model("BAAI/bge-large-zh-v1.5") == 4096
    assert get_vector_size_for_model("bge-large") == 4096


def test_get_vector_size_for_model_invalid_model_raises():
    with pytest.raises(ValueError, match="Unsupported embedding model"):
        get_vector_size_for_model("unsupported-embedding-model")


def test_get_vector_size_for_model_empty_name_raises():
    with pytest.raises(ValueError, match="Embedding model name cannot be empty"):
        get_vector_size_for_model("")
