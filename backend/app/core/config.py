from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, quote

from pydantic_settings import BaseSettings
from pydantic import SecretStr

BASE_DIR = Path(__file__).resolve().parent.parent.parent


class Config(BaseSettings):
    # MySQL
    database_type: str = 'mysql'
    connector: str = 'pymysql'
    database_host: str = 'localhost'
    database_port: int = 3306
    database_name: str = ''
    database_username: str = ''
    database_password: SecretStr = SecretStr('')
    database_socket: Optional[str] = None

    # Qdrant
    qdrant_url: str = 'http://localhost:6333'
    qdrant_api_key: str = ''   # 本地部署可留空，云端部署时填写

    # Redis
    redis_host: str = '127.0.0.1'
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: SecretStr = SecretStr('')

    # JWT
    jwt_secret_key: SecretStr = SecretStr('change-me-in-production')
    jwt_algorithm: str = 'HS256'
    jwt_access_token_expire_minutes: int = 5
    jwt_refresh_token_expire_days: int = 7

    # Encryption
    fernet_key: SecretStr = SecretStr('')

    # File upload
    upload_dir: str = '/tmp/ai_studio/uploads'
    max_upload_size_mb: int = 50

    # Celery
    celery_broker_url: str = 'redis://localhost:6379/1'
    celery_result_backend: str = 'redis://localhost:6379/2'

    def _with_redis_password(self, url: str) -> str:
        """URL 未携带凭据时注入 ``redis_password``。

        必须与 ``app/core/redis.py`` 的行为保持一致：该文件用 ``redis_password``
        认证，而 Celery 直接使用 ``celery_broker_url`` 原文。若部署时设置了
        ``REDIS_PASSWORD`` 但 ``CELERY_BROKER_URL`` 未内嵌密码，就会出现
        「Redis 客户端能连、Celery worker 报 NOAUTH」的分裂状态，表现为文档处理
        任务永远不被消费、状态卡在 pending，而日志里没有任何明显线索。
        """
        password = self.redis_password.get_secret_value()
        if not password or not url:
            return url
        parsed = urlparse(url)
        if parsed.password or not parsed.hostname:
            return url
        netloc = f"{parsed.username or ''}:{quote(password, safe='')}@{parsed.hostname}"
        if parsed.port:
            netloc = f"{netloc}:{parsed.port}"
        return parsed._replace(netloc=netloc).geturl()

    def get_celery_broker_url(self) -> str:
        """Celery broker 地址（必要时注入 Redis 密码）"""
        return self._with_redis_password(self.celery_broker_url)

    def get_celery_result_backend(self) -> str:
        """Celery 结果后端地址（必要时注入 Redis 密码）"""
        return self._with_redis_password(self.celery_result_backend)

    # embedding
    # 默认使用本地 sentence-transformers 模型，保证企业内网数据不出网。
    embedding_provider: str = 'sentence-transformers'
    embedding_model: str = 'BAAI/bge-base-zh-v1.5'
    embedding_device: str = 'cpu'  # 本地模型推理设备：cpu / cuda
    embedding_api_key: SecretStr = SecretStr('')
    embedding_api_base: str = ''

    # Ollama
    ollama_base_url: str = 'http://localhost:11434'

    model_config = {'env_file': str(BASE_DIR / '.env')}


config = Config()
