from pathlib import Path
import os
from typing import Optional
from urllib.parse import quote, urlparse

from pydantic_settings import BaseSettings
from pydantic import SecretStr

BASE_DIR = Path(__file__).resolve().parent.parent.parent

# 允许在测试 / CI 环境下跳过 .env 读取。
# 默认行为不变（读取 backend/.env）；设置 AI_STUDIO_SKIP_ENV_FILE=1 时，
# 仅使用下方字段默认值与环境变量，从而让测试不依赖本机凭据文件——
# 否则任何缺少 .env 的环境都无法导入 app.core.config，整个测试套件在
# collection 阶段即失败。生产运行不受影响。
_SKIP_ENV_FILE: bool = os.environ.get('AI_STUDIO_SKIP_ENV_FILE', '').strip().lower() in {
    '1',
    'true',
    'yes',
    'on',
}
_ENV_FILE: Optional[str] = None if _SKIP_ENV_FILE else str(BASE_DIR / '.env')


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

    # CORS：允许跨域访问的前端源（逗号分隔）。默认值为开发用 localhost:3000。
    # 标准部署中前端与 API 经 vite/nginx 同域代理，浏览器侧不触发跨域；
    # 仅当浏览器直接跨域访问后端时才需配置。设为空字符串表示拒绝任何跨域请求，
    # 杜绝原先 ``allow_origins=["*"]`` + ``allow_credentials=True`` 导致的凭证泄露风险
    # （详见 docs/review/01-backend.md S1）。
    cors_origins: str = 'http://localhost:3000'

    # Celery
    celery_broker_url: str = 'redis://localhost:6379/1'
    celery_result_backend: str = 'redis://localhost:6379/2'

    # 工作流执行整体超时（秒）。A3：防止单个工作流无限挂起占用请求。
    # 单点 LLM 调用另有客户端超时（utils/llm.py），此处约束整条 DAG 的执行预算。
    workflow_execution_timeout_seconds: int = 600

    # embedding
    # 默认使用本地 sentence-transformers 模型，保证企业内网数据不出网。
    # 如需切换外部 API，可将 embedding_provider 改为 openai/azure/siliconflow/ollama。
    embedding_provider: str = 'sentence-transformers'
    embedding_model: str = 'BAAI/bge-base-zh-v1.5'
    embedding_device: str = 'cpu'  # 本地模型推理设备：cpu / cuda
    embedding_api_key: SecretStr = SecretStr('')
    embedding_api_base: str = ''

    # 检索
    # 向量召回的相似度下限。0.0 表示不做阈值过滤，交由后续精排阶段裁量；
    # 调高可提升精确率但会漏召回，建议在评测集上标定后再调整。
    retrieval_score_threshold: float = 0.0

    # Reranker（本地 CrossEncoder 精排）
    # 默认关闭：精排会引入额外推理延迟，且不同知识库的最优候选数不同，
    # 必须在评测集上标定后再按知识库开启，不应默认对所有流量生效。
    reranker_enabled: bool = False
    reranker_model: str = 'BAAI/bge-reranker-v2-m3'
    reranker_device: str = 'cpu'   # 本地模型推理设备：cpu / mps / cuda
    # 宽召回候选数：精排只能对已召回的候选重排，候选集过小会限制精排的上限。
    # 该值直接决定延迟（精排成本与候选数线性相关），需与质量一并标定。
    reranker_candidate_k: int = 20
    reranker_batch_size: int = 32
    # 精排输入截断长度。过长会显著拖慢 CPU 推理，而中文段落的关键信息通常在前部。
    reranker_max_length: int = 512

    # Ollama
    ollama_base_url: str = 'http://localhost:11434'

    # LLM 请求超时（秒）。用于 openai / anthropic / azure / custom 等远端供应商：
    # 超时后由服务端主动失败并返回明确错误，避免请求长时间悬挂
    # （langchain-openai 默认 600s，前端会先于其超时）。
    # Ollama 本地推理较慢（首次调用需加载模型），单独走 600s，不由此值控制。
    llm_request_timeout: int = 120

    # 出站访问策略（SSRF 防护），作用于插件调用与 Agent 的 API 工具。
    # True（默认，安全基线）：拒绝访问私有地址、环回、链路本地（含云元数据
    #   169.254.169.254）、保留与组播网段，避免平台被用作 SSRF / 内网探测跳板。
    # 置为 False 会**关闭**该校验——仅在部署环境确需让插件访问内网服务
    #   （如对接内部 CRM / 私有 API）时使用，属有意识的降级，
    #   应同时通过网络层出站策略限制可达范围。详见 app/utils/net_guard.py
    plugin_block_private_network: bool = True

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

    @property
    def cors_origins_list(self) -> list:
        """解析 CORS 允许源为列表；空字符串返回空列表（拒绝任何跨域）。"""
        return [o.strip() for o in self.cors_origins.split(',') if o.strip()]

    model_config = {'env_file': _ENV_FILE}


config = Config()
