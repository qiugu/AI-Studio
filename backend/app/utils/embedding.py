"""向量化（Embedding）工具，支持多个提供商"""
import logging
import time
from typing import List

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


def get_embedding_client(provider: str = "siliconflow", model: str = "BAAI/bge-large-zh-v1.5") -> EmbeddingClient:
    """工厂函数：获取向量化客户端"""
    return EmbeddingClient(provider=provider, model=model)
