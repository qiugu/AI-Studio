"""向量化（Embedding）工具，支持多个提供商"""
import logging
import os
import time
from typing import List, Optional

from app.core.config import config

logger = logging.getLogger(__name__)


def _request_with_retry(request_fn, *, timeout: int = 60, retries: int = 3):
    """对网络波动导致的短暂中断做有限重试。"""
    last_error = None
    for attempt in range(retries):
        try:
            return request_fn()
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt == retries - 1:
                raise
            if isinstance(exc, (ConnectionError, TimeoutError)):
                logger.warning("Embedding request failed, retrying (%s/%s): %s", attempt + 1, retries, exc)
            else:
                logger.warning("Embedding request failed with transient error, retrying (%s/%s): %s", attempt + 1, retries, exc)
            time.sleep(min(2 ** attempt, 5))
    raise last_error


class EmbeddingClient:
    """向量化客户端，支持OpenAI、Azure等提供商"""

    def __init__(self, provider: str = "openai", model: str = "text-embedding-3-small"):
        """
        初始化向量化客户端

        Args:
            provider: 提供商名称 (openai, azure, ollama等)
            model: 模型名称
        """
        self.provider = provider
        self.model = model
        self._validate_config()

    def _validate_config(self):
        """验证配置"""
        if self.provider == "openai":
            if not config.embedding_api_key.get_secret_value():
                raise ValueError("OPENAI_API_KEY is not set")
        elif self.provider == "azure":
            if not (config.embedding_api_key.get_secret_value() and config.embedding_api_base):
                raise ValueError("AZURE_API_KEY and AZURE_API_BASE are required")
        elif self.provider == "ollama":
            if not config.ollama_base_url:
                raise ValueError("OLLAMA_BASE_URL is not set")
        elif self.provider == "sentence-transformers":
            # 本地模型，无需外部密钥；模型以 HuggingFace repo id 标识
            if not self.model:
                raise ValueError("model is required for sentence-transformers provider")

    def embed(self, texts: List[str]) -> List[List[float]]:
        """
        对文本进行向量化

        Args:
            texts: 文本列表

        Returns:
            向量列表，每个向量是浮点数列表
        """
        if self.provider == "openai":
            return self._embed_openai(texts)
        elif self.provider == "azure":
            return self._embed_azure(texts)
        elif self.provider == "ollama":
            return self._embed_ollama(texts)
        elif self.provider == "siliconflow":
            return self._embed_siliconflow(texts)
        elif self.provider == "sentence-transformers":
            return self._embed_sentence_transformers(texts)
        else:
            raise ValueError(f"Unsupported provider: {self.provider}")

    def _embed_openai(self, texts: List[str]) -> List[List[float]]:
        """OpenAI embedding"""
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError("openai is required. Install it with: pip install openai")

        client = OpenAI(api_key=config.embedding_api_key.get_secret_value())
        response = client.embeddings.create(
            model=self.model,
            input=texts,
        )
        return [item.embedding for item in response.data]

    def _embed_azure(self, texts: List[str]) -> List[List[float]]:
        """Azure OpenAI embedding"""
        try:
            from openai import AzureOpenAI
        except ImportError:
            raise ImportError("openai is required. Install it with: pip install openai")

        client = AzureOpenAI(
            api_key=config.embedding_api_key.get_secret_value(),
            api_version="2024-02-15-preview",
            azure_endpoint=config.embedding_api_base,
        )
        response = client.embeddings.create(
            model=self.model,
            input=texts,
        )
        return [item.embedding for item in response.data]
    
    def _embed_siliconflow(self, texts: List[str]) -> List[List[float]]:
        """Siliconflow embedding"""
        try:
            import requests
        except ImportError:
            raise ImportError("requests is required. Install it with: pip install requests")

        def do_request():
            response = requests.post(
                config.embedding_api_base,
                json={"model": self.model, "input": texts},
                headers={
                    "Authorization": f"Bearer {config.embedding_api_key.get_secret_value()}",
                    "Content-Type": "application/json",
                },
                timeout=60,
            )
            response.raise_for_status()
            return response.json()["data"]

        data = _request_with_retry(do_request)
        return [item['embedding'] for item in data]

    def _embed_ollama(self, texts: List[str]) -> List[List[float]]:
        """Ollama embedding（本地模型）"""
        try:
            import requests
        except ImportError:
            raise ImportError("requests is required. Install it with: pip install requests")

        embeddings = []
        for text in texts:
            def do_request():
                response = requests.post(
                    f"{config.ollama_base_url}/api/embeddings",
                    json={"model": self.model, "prompt": text},
                    timeout=60,
                )
                response.raise_for_status()
                return response.json()["embedding"]

            embeddings.append(_request_with_retry(do_request, timeout=60))
        return embeddings

    def _embed_sentence_transformers(self, texts: List[str]) -> List[List[float]]:
        """本地 sentence-transformers 模型向量化。

        模型按 (model, device) 进程级缓存，仅首次加载时读取权重；
        后续任务复用同一实例，避免重复占用内存与启动开销。
        """
        device = getattr(config, "embedding_device", "cpu") or "cpu"
        model = _get_sentence_transformer_model(self.model, device)
        vectors = model.encode(
            texts,
            batch_size=32,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return vectors.tolist()


# 进程级模型缓存：key = (model_name, device)
_ST_MODEL_CACHE: dict = {}


def _get_sentence_transformer_model(model_name: str, device: str):
    """懒加载并缓存 sentence-transformers 模型（每个进程只加载一次）。"""
    try:
        import torch
        from sentence_transformers import SentenceTransformer
    except ImportError:
        raise ImportError(
            "sentence-transformers is required for local embedding. "
            "Install it with: pip install sentence-transformers"
        )

    # 单进程内限制 OpenMP 线程数。与 celery_app 中的环境变量配合，避免在 fork 子进程
    # 或多个并发 worker 中叠加大量 OpenMP 线程导致资源争用与不稳定。
    # 默认 1 与线上 celery 场景保持一致；**单进程的离线任务**（如
    # scripts/rebuild_knowledge_vectors.py）无 fork 叠加问题，可设
    # ``EMBEDDING_TORCH_THREADS`` 提升吞吐（审查建议 P1-2）。
    try:
        torch.set_num_threads(int(os.environ.get("EMBEDDING_TORCH_THREADS", "1")))
    except Exception:  # noqa: BLE001
        pass

    cache_key = (model_name, device)
    if cache_key not in _ST_MODEL_CACHE:
        logger.info("Loading local embedding model %s on device=%s", model_name, device)
        _ST_MODEL_CACHE[cache_key] = SentenceTransformer(model_name, device=device)
    return _ST_MODEL_CACHE[cache_key]


def get_embedding_client(
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> EmbeddingClient:
    """工厂函数：获取向量化客户端。

    provider / model 缺省时回退到全局配置（config.embedding_provider /
    config.embedding_model），避免此前硬编码 siliconflow 导致的配置失效问题。
    """
    provider = provider or config.embedding_provider
    model = model or config.embedding_model
    return EmbeddingClient(provider=provider, model=model)
