from pathlib import Path
from typing import Optional

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

    # embedding
    embedding_provider: str = 'openai'
    embedding_model: str = 'text-embedding-3-small'
    embedding_api_key: SecretStr = SecretStr('')
    embedding_api_base: str = ''

    model_config = {'env_file': str(BASE_DIR / '.env')}


config = Config()
