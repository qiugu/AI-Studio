# AI-Studio 核心机制设计

## 1. 认证与RBAC

### 1.1 JWT认证流程

```
客户端                     服务端
  │                         │
  │──POST /api/auth/login──►│
  │   {email, password}     │
  │                         │ 验证密码(passlib+bcrypt)
  │                         │ 生成access_token(30min) + refresh_token(7d)
  │◄──{access_token, ──────│
  │    refresh_token,       │
  │    user_info}           │
  │                         │
  │──GET /api/xxx──────────►│
  │   Authorization:        │ 验证access_token
  │   Bearer <token>        │ 提取user_id + tenant_id
  │                         │
  │──POST /api/auth/refresh►│
  │   {refresh_token}       │ 验证refresh_token → 新access_token
  │◄──{access_token}────────│
```

### 1.2 RBAC权限模型

```
User ──多对多──► Role ──多对多──► Permission
                      │
                      │ 资源+操作组合
                      │
                      ▼
              resource:action
              如: model:create
                  prompt:read
                  workflow:execute
```

**权限矩阵**:

| 资源 | 操作 | 说明 |
|------|------|------|
| user | create, read, update, delete | 用户管理 |
| role | create, read, update, delete | 角色管理 |
| provider | create, read, update, delete, execute | 供应商管理 |
| model | create, read, update, delete, execute | 模型管理 |
| prompt | create, read, update, delete, execute | Prompt管理 |
| kb | create, read, update, delete, execute | 知识库管理 |
| workflow | create, read, update, delete, execute | 工作流管理 |
| agent | create, read, update, delete, execute | Agent管理 |
| plugin | create, read, update, delete, execute | 插件管理 |
| audit | read, export | 审计日志 |
| tenant | read, update | 租户管理 |
| api_key | create, read, delete, update | API密钥 |

### 1.3 权限依赖实现

```python
# app/core/security.py
from passlib.context import CryptContext
from jose import jwt
from datetime import datetime, timedelta

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

SECRET_KEY = "your-secret-key"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE = 30  # minutes
REFRESH_TOKEN_EXPIRE = 7 * 24 * 60  # minutes

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)

def create_access_token(user_id: int, tenant_id: int) -> str:
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE)
    return jwt.encode({"sub": str(user_id), "tid": tenant_id, "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)

def create_refresh_token(user_id: int) -> str:
    expire = datetime.utcnow() + timedelta(minutes=REFRESH_TOKEN_EXPIRE)
    return jwt.encode({"sub": str(user_id), "type": "refresh", "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)
```

```python
# app/core/dependencies.py
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from app.core.database import get_session
from app.core.security import decode_token
from app.models import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

async def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_session)) -> User:
    payload = decode_token(token)
    user_id = int(payload.get("sub"))
    user = db.query(User).filter(User.id == user_id, User.deleted_at.is_(None)).first()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid token")
    return user

def require_permission(resource: str, action: str):
    def checker(current_user: User = Depends(get_current_user), db: Session = Depends(get_session)):
        user_perms = (
            db.query(Permission)
            .join(role_permission)
            .join(user_role)
            .filter(user_role.c.user_id == current_user.id)
            .filter(Permission.resource == resource, Permission.action == action)
            .first()
        )
        if not user_perms:
            raise HTTPException(status_code=403, detail=f"No {action} permission for {resource}")
        return current_user
    return checker
```

### 1.4 租户隔离中间件

```python
# app/middleware/tenant.py
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import HTTPException
from app.core.database import get_session
from app.models.tenant import Tenant

class TenantMiddleware(BaseHTTPMiddleware):
    # 不需要租户上下文的白名单路径（注册/登录/刷新 token 无需校验租户状态）
    SKIP_PATHS = {"/api/auth/login", "/api/auth/register", "/api/auth/refresh"}

    async def dispatch(self, request, call_next):
        if request.url.path in self.SKIP_PATHS:
            return await call_next(request)

        user = getattr(request.state, 'user', None)
        if user and not user.is_platform_admin:
            # 校验租户是否存在且未被注销/禁用
            db = next(get_session())
            tenant = db.query(Tenant).filter(
                Tenant.id == user.tenant_id,
                Tenant.deleted_at.is_(None)
            ).first()
            if not tenant:
                raise HTTPException(status_code=403, detail="TENANT_NOT_FOUND")
            if not tenant.status:
                raise HTTPException(status_code=403, detail="TENANT_DISABLED")
            request.state.tenant_id = user.tenant_id
            request.state.tenant = tenant

        response = await call_next(request)
        return response
```

### 1.5 BaseRepository — 租户隔离基类

所有 Repository 继承此基类，构造时绑定 `tenant_id`，所有查询自动附加过滤条件，从根本上防止跨租户数据泄漏。

```python
# app/repositories/base.py
from typing import Generic, TypeVar, Type
from sqlalchemy.orm import Session
from sqlalchemy import func

T = TypeVar("T")

class BaseRepository(Generic[T]):
    """
    泛型 Repository 基类。
    - tenant_id=None 表示平台超级管理员，跳过租户过滤，可查所有租户数据
    - 普通用户必须传入 tenant_id，所有查询强制附加 tenant_id 条件
    """
    def __init__(self, model: Type[T], db: Session, tenant_id: int | None = None):
        self.model = model
        self.db = db
        self.tenant_id = tenant_id

    def _tenant_filter(self) -> list:
        """普通租户过滤：仅返回当前租户数据"""
        if self.tenant_id is None:
            return []  # 超级管理员不过滤
        return [self.model.tenant_id == self.tenant_id]

    def _tenant_or_public_filter(self) -> list:
        """公共资源过滤：返回当前租户数据 + 平台公共数据（tenant_id IS NULL）
        用于 ai_models、plugins 等支持公共资源的表。
        """
        if self.tenant_id is None:
            return []
        from sqlalchemy import or_
        return [or_(
            self.model.tenant_id == self.tenant_id,
            self.model.tenant_id == None
        )]

    def get_by_id(self, id: int) -> T | None:
        return self.db.query(self.model).filter(
            self.model.id == id,
            *self._tenant_filter()
        ).first()

    def list(self, page: int = 1, page_size: int = 20, **filters) -> tuple[list[T], int]:
        query = self.db.query(self.model).filter(*self._tenant_filter())
        for key, value in filters.items():
            if value is not None:
                query = query.filter(getattr(self.model, key) == value)
        total = query.count()
        items = query.offset((page - 1) * page_size).limit(page_size).all()
        return items, total

    def count(self, **filters) -> int:
        query = self.db.query(func.count(self.model.id)).filter(*self._tenant_filter())
        for key, value in filters.items():
            if value is not None:
                query = query.filter(getattr(self.model, key) == value)
        return query.scalar()
```

Repository 工厂依赖（自动绑定当前用户 tenant_id）：

```python
# app/core/dependencies.py 补充
from app.repositories.base import BaseRepository

def get_repo(repo_class: Type[BaseRepository]):
    """Repository 工厂依赖，自动从当前登录用户绑定 tenant_id"""
    def _dep(
        db: Session = Depends(get_session),
        current_user: User = Depends(get_current_user)
    ) -> BaseRepository:
        # 超级管理员传 None，跳过租户过滤
        tenant_id = None if current_user.is_platform_admin else current_user.tenant_id
        return repo_class(db=db, tenant_id=tenant_id)
    return _dep
```

### 1.6 超级管理员依赖守卫

```python
# app/core/dependencies.py 补充

async def require_platform_admin(
    current_user: User = Depends(get_current_user)
) -> User:
    """
    仅平台超级管理员（is_platform_admin=True）可访问的接口守卫。
    不走普通 RBAC 权限表，直接检查 users.is_platform_admin 字段。
    用于 /api/admin/* 所有接口。
    """
    if not current_user.is_platform_admin:
        raise ForbiddenException()
    return current_user
```

### 1.7 QuotaService — 配额检查

在 Service 层创建资源前调用，超出配额时抛出 `QuotaExceededException(429)`。

```python
# app/services/quota.py
from app.core.exceptions import QuotaExceededException

class QuotaService:
    """
    配额检查服务，由各业务 Service 在创建受限资源前调用。

    调用时机:
      UserService.create_user()       → check_user_quota()
      AIModelService.create_model()   → check_model_quota()
    """
    def __init__(self, tenant_repo, user_repo, model_repo):
        self.tenant_repo = tenant_repo
        self.user_repo = user_repo
        self.model_repo = model_repo

    def check_user_quota(self, tenant_id: int) -> None:
        tenant = self.tenant_repo.get_by_id(tenant_id)
        current = self.user_repo.count(status=True)
        if current >= tenant.max_users:
            raise QuotaExceededException("users")

    def check_model_quota(self, tenant_id: int) -> None:
        tenant = self.tenant_repo.get_by_id(tenant_id)
        current = self.model_repo.count(status=True)
        if current >= tenant.max_models:
            raise QuotaExceededException("models")
```

### 1.8 租户生命周期管理

```
租户生命周期状态机:

  正常 (status=True, deleted_at=NULL)
    │
    ├─ 禁用 → status=False
    │         TenantMiddleware 拦截所有请求，返回 403 TENANT_DISABLED
    │         已登录 Token 在下次请求时被拒绝（不需要主动吊销）
    │
    └─ 注销 → deleted_at=now()（软删除）
              触发 Celery 异步任务 cleanup_tenant_data:
                1. 删除 Qdrant 中该 tenant_id 的所有向量 Point
                2. 删除文件系统/OSS 中 uploads/{tenant_id}/ 目录
                3. 级联软删除业务数据：
                   users / ai_providers / knowledge_bases /
                   workflows / agents / conversations / messages
                4. audit_logs / token_usages 永久保留（合规 & 计费依据）
                5. 90 天后可通过定时任务物理清除软删除数据（可配置）

数据保留策略:
  - audit_logs:    永久保留
  - token_usages:  永久保留（计费依据）
  - 其他数据:      软删除后 90 天可物理清除（TENANT_DATA_RETENTION_DAYS 配置项）
```

### 1.9 审计日志中间件

```python
# app/middleware/audit.py
import json
from starlette.middleware.base import BaseHTTPMiddleware

class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        # 异步记录审计日志(写操作才记录)
        if request.method in ("POST", "PUT", "DELETE", "PATCH"):
            await self._log(request, response)
        return response

    async def _log(self, request, response):
        # 提取用户、操作类型、资源等
        # 写入audit_logs表
        pass
```

---

## 2. LangChain集成层

### 2.1 LLM客户端封装

```python
# app/utils/llm.py
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from app.models.ai_model import AIModel
from app.models.ai_provider import AIProvider

class LLMClient:
    def __init__(self, provider: AIProvider, model: AIModel):
        self.provider = provider
        self.model = model
        self.chain: BaseChatModel = self._build_chain()

    def _build_chain(self) -> BaseChatModel:
        provider_type = self.provider.provider_type

        if provider_type == "openai":
            return ChatOpenAI(
                model=self.model.name,
                openai_api_key=self._decrypt_key(self.provider.api_key_encrypted),
                openai_api_base=self.provider.api_base_url,
                max_tokens=self.model.max_output_tokens,
            )
        elif provider_type == "anthropic":
            return ChatAnthropic(
                model=self.model.name,
                anthropic_api_key=self._decrypt_key(self.provider.api_key_encrypted),
                anthropic_api_url=self.provider.api_base_url,
                max_tokens=self.model.max_output_tokens,
            )
        elif provider_type == "azure":
            return ChatOpenAI(
                model=self.model.name,
                openai_api_key=self._decrypt_key(self.provider.api_key_encrypted),
                openai_api_base=self.provider.api_base_url,
                openai_api_type="azure",
                openai_api_version="2024-02-01",
            )
        # ... 其他供应商
        else:
            raise ValueError(f"Unsupported provider type: {provider_type}")

    def _decrypt_key(self, encrypted: str) -> str:
        from app.utils.encryption import fernet_decrypt
        return fernet_decrypt(encrypted)

    async def ainvoke(self, messages, **kwargs):
        return await self.chain.ainvoke(messages, **kwargs)

    async def astream(self, messages, **kwargs):
        async for chunk in self.chain.astream(messages, **kwargs):
            yield chunk
```

### 2.2 Embedding客户端封装

```python
# app/utils/embedding.py
from langchain_openai import OpenAIEmbeddings
from langchain_community.embeddings import HuggingFaceEmbeddings

class EmbeddingClient:
    def __init__(self, provider: AIProvider, model: AIModel):
        self.provider = provider
        self.model = model
        self.embedder = self._build()

    def _build(self):
        if self.provider.provider_type in ("openai", "azure"):
            return OpenAIEmbeddings(
                model=self.model.name,
                openai_api_key=self._decrypt_key(self.provider.api_key_encrypted),
                openai_api_base=self.provider.api_base_url,
            )
        elif self.provider.provider_type == "local":
            return HuggingFaceEmbeddings(model_name=self.model.name)
        # ... 其他

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return await self.embedder.aembed_documents(texts)

    async def embed_query(self, text: str) -> list[float]:
        return await self.embedder.aembed_query(text)
```

### 2.3 API Key加密工具

```python
# app/utils/encryption.py
from cryptography.fernet import Fernet
import os

# 从环境变量读取主密钥，不存在则自动生成
FERNET_KEY = os.getenv("FERNET_KEY", Fernet.generate_key().decode())
fernet = Fernet(FERNET_KEY.encode())

def fernet_encrypt(plaintext: str) -> str:
    return fernet.encrypt(plaintext.encode()).decode()

def fernet_decrypt(ciphertext: str) -> str:
    return fernet.decrypt(ciphertext.encode()).decode()
```

---

## 3. 知识库处理流水线

### 3.1 文档处理流程

```
文档上传 → 文件存储(本地/OSS)
         → 创建文档记录(status=PENDING)
         → Celery异步任务触发
            ├── 解析文档(python-docx/pypdf2)
            ├── 文本分割(RecursiveCharacterTextSplitter)
            ├── Embedding向量化(EmbeddingClient)
            ├── 存入Qdrant（upsert points，content存于payload）
            └── 更新文档状态(status=COMPLETED/FAILED)
```

**当前实现状态**（阶段4）：
- ✅ 文档上传接口已实现（`POST /knowledge/knowledge-bases/{kb_id}/documents/upload`）
- ✅ 文档解析工具已实现（`DocumentParser` 支持 PDF/Word/Markdown/TXT）
- ✅ 文本分块工具已实现（`TextSplitter` 使用 LangChain 的 `RecursiveCharacterTextSplitter`）
- ✅ 向量化客户端已实现（`EmbeddingClient` 支持 OpenAI/Azure/Ollama）
- ✅ Qdrant Collection 管理已实现
- ⏳ Celery 异步任务集成待完成（文档处理任务需配置 worker）
- ⏳ 文件持久化存储待完成（当前使用临时目录）

### 3.2 文档解析工具

```python
# app/utils/document.py
from langchain_text_splitters import RecursiveCharacterTextSplitter
import docx, PyPDF2, os

class DocumentParser:
    """文档解析器，支持多种格式文档转文本"""

    SUPPORTED_TYPES = ["pdf", "docx", "txt", "md"]

    @staticmethod
    def parse(file_path: str) -> str:
        """解析文档并返回纯文本内容"""
        ext = os.path.splitext(file_path)[1].lower().lstrip(".")
        if ext not in DocumentParser.SUPPORTED_TYPES:
            raise ValueError(f"Unsupported file type: {ext}")

        if ext == "pdf":
            return DocumentParser._parse_pdf(file_path)
        elif ext == "docx":
            return DocumentParser._parse_docx(file_path)
        elif ext in ("txt", "md"):
            return DocumentParser._parse_txt(file_path)

    @staticmethod
    def _parse_pdf(path: str) -> str:
        """PDF 解析（使用 PyPDF2）"""
        text = []
        with open(path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            for page in reader.pages:
                text.append(page.extract_text())
        return "\n".join(text)

    @staticmethod
    def _parse_docx(path: str) -> str:
        """Word 文档解析（使用 python-docx）"""
        doc = docx.Document(path)
        return "\n".join([para.text for para in doc.paragraphs])

    @staticmethod
    def _parse_txt(path: str) -> str:
        """文本文件解析"""
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

class TextSplitter:
    """文本分块器，使用递归策略分割长文本"""

    def __init__(self, chunk_size: int = 500, chunk_overlap: int = 50):
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", "。", "！", "？", ".", " ", ""],
            length_function=len,
        )

    def split(self, text: str) -> list[str]:
        """将文本分割为多个块"""
        return self.splitter.split_text(text)
```

**使用示例**：
```python
from app.utils.document import DocumentParser, TextSplitter

# 解析文档
parser = DocumentParser()
text = parser.parse("/path/to/document.pdf")

# 分块处理
splitter = TextSplitter(chunk_size=500, chunk_overlap=50)
chunks = splitter.split(text)  # 返回 list[str]
```

### 3.3 Qdrant客户端管理

```python
# app/core/vector_db.py
import logging
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, HnswConfigDiff
from app.core.config import config

logger = logging.getLogger(__name__)

_qdrant_client: QdrantClient | None = None

def get_qdrant_client() -> QdrantClient:
    global _qdrant_client
    if _qdrant_client is None:
        _qdrant_client = QdrantClient(
            url=config.qdrant_url,
            api_key=config.qdrant_api_key or None,
            timeout=30,
        )
    return _qdrant_client

def init_vector_db() -> None:
    """应用启动时验证Qdrant连通性"""
    try:
        client = get_qdrant_client()
        client.get_collections()
        logger.info("Qdrant connection verified")
    except Exception as e:
        logger.warning("Could not connect to Qdrant: %s", e)

def get_or_create_collection(kb_id: int, vector_size: int = 1536) -> str:
    """确保知识库对应的Collection存在，返回collection_name"""
    collection_name = f"kb_{kb_id}"
    client = get_qdrant_client()
    existing = {c.name for c in client.get_collections().collections}
    if collection_name not in existing:
        client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
            hnsw_config=HnswConfigDiff(m=16, ef_construct=100),
        )
        logger.info("Created Qdrant collection: %s", collection_name)
    return collection_name
```

### 3.4 Embedding 向量化客户端

```python
# app/utils/embedding.py
from langchain_openai import OpenAIEmbeddings
from langchain_community.embeddings import HuggingFaceEmbeddings
from app.core.config import config

class EmbeddingClient:
    """Embedding 客户端，支持多个向量模型提供商"""

    def __init__(self, provider_type: str, model_name: str, api_key: str = None, api_base: str = None):
        self.provider_type = provider_type
        self.model_name = model_name
        self.api_key = api_key
        self.api_base = api_base
        self.embedder = self._build()

    def _build(self):
        """构建对应的 Embeddings 实例"""
        if self.provider_type == "openai":
            return OpenAIEmbeddings(
                model=self.model_name,
                openai_api_key=self.api_key,
                openai_api_base=self.api_base,
            )
        elif self.provider_type == "azure":
            return OpenAIEmbeddings(
                model=self.model_name,
                openai_api_key=self.api_key,
                openai_api_base=self.api_base,
                openai_api_type="azure",
            )
        elif self.provider_type == "ollama":
            return HuggingFaceEmbeddings(
                model_name=self.model_name,
            )
        else:
            raise ValueError(f"Unsupported embedding provider: {self.provider_type}")

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """批量向量化文本列表"""
        return self.embedder.embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        """向量化单个查询文本"""
        return self.embedder.embed_query(text)

def get_embedding_client() -> EmbeddingClient:
    """获取配置的 Embedding 客户端实例"""
    return EmbeddingClient(
        provider_type=config.embedding_provider,
        model_name=config.embedding_model,
        api_key=config.embedding_api_key,
        api_base=config.embedding_api_base,
    )
```

**常用向量模型及维度**：
- OpenAI `text-embedding-3-small`: 1536 维
- OpenAI `text-embedding-3-large`: 3072 维
- BAAI `bge-m3`: 1024 维
- Azure OpenAI `text-embedding-ada-002`: 1536 维

### 3.5 知识库检索

```python
# app/services/knowledge.py (检索部分)
from qdrant_client.models import Filter, FieldCondition, MatchValue, ScoredPoint
from app.core.vector_db import get_qdrant_client
from app.utils.embedding import get_embedding_client

def search(
    self,
    kb_id: int,
    query_text: str,
    top_k: int = 5,
    score_threshold: float = 0.7,
) -> list[dict]:
    """语义检索知识库内容"""
    # 1. 查询文本向量化
    embedding_client = get_embedding_client()
    query_vector = embedding_client.embed_query(query_text)

    # 2. 在 Qdrant 中搜索
    client = get_qdrant_client()
    collection_name = f"kb_{kb_id}"

    results: list[ScoredPoint] = client.search(
        collection_name=collection_name,
        query_vector=query_vector,
        limit=top_k,
        score_threshold=score_threshold,   # Qdrant原生过滤，减少传输
        with_payload=True,                 # payload中含content和metadata
    )

    # 3. 格式化返回结果
    return [
        {
            "chunk_id": r.payload.get("chunk_id"),
            "doc_id": r.payload.get("doc_id"),
            "content": r.payload.get("content"),
            "source_page": r.payload.get("source_page"),
            "score": r.score,
        }
        for r in results
    ]
```

**检索流程**：
1. 用户输入查询文本
2. 通过 Embedding 客户端向量化查询文本
3. 在对应的 Qdrant Collection 中进行相似度搜索
4. 返回最相关的 top_k 个结果（包含相似度评分）

**返回结果结构**：
```json
{
  "chunk_id": 123,
  "doc_id": 45,
  "content": "文档片段内容...",
  "source_page": 5,
  "score": 0.85  // 相似度评分（0-1）
}
```

### 3.6 Celery 异步任务（待完成）

```python
# app/services/knowledge_processor.py (待实现)
from celery import shared_task
from app.utils.document import DocumentParser, TextSplitter
from app.utils.embedding import get_embedding_client
from app.core.vector_db import get_qdrant_client
from app.repositories.knowledge import KnowledgeDocumentRepository, KnowledgeChunkRepository
from app.models.knowledge_document import DocumentStatus

@shared_task
def process_document_task(doc_id: int, file_path: str, tenant_id: int):
    """
    异步文档处理任务
    流程：解析 → 分块 → 向量化 → 存入 Qdrant → 更新状态
    """
    try:
        # 1. 解析文档
        parser = DocumentParser()
        text = parser.parse(file_path)

        # 2. 文本分块
        splitter = TextSplitter(chunk_size=500, chunk_overlap=50)
        chunks = splitter.split(text)

        # 3. 向量化
        embedding_client = get_embedding_client()
        vectors = embedding_client.embed_documents(chunks)

        # 4. 存入 Qdrant
        client = get_qdrant_client()
        collection_name = f"kb_{kb_id}"

        points = [
            PointStruct(
                id=str(uuid.uuid4()),
                vector=vector,
                payload={
                    "chunk_id": chunk_id,
                    "doc_id": doc_id,
                    "content": chunk,
                    "tenant_id": tenant_id,
                }
            )
            for chunk_id, (chunk, vector) in enumerate(zip(chunks, vectors))
        ]

        client.upsert(collection_name=collection_name, points=points)

        # 5. 更新文档状态为 COMPLETED
        doc_repo = KnowledgeDocumentRepository(db=db, tenant_id=tenant_id)
        doc_repo.update(doc_id, status=DocumentStatus.COMPLETED)

    except Exception as e:
        # 更新文档状态为 FAILED，记录错误信息
        doc_repo.update(doc_id, status=DocumentStatus.FAILED, error_message=str(e))
```

**Celery 配置**（待完成）：
```bash
# 启动 Celery worker
celery -A app.core.celery_app worker --loglevel=info

# 启动 Celery beat（定时任务调度器，可选）
celery -A app.core.celery_app beat --loglevel=info
```

**注意事项**：
- Celery broker 需配置 Redis（`config.redis_url`）
- Worker 进程需独立运行，不依赖 FastAPI 主进程
- 任务失败时会记录 `error_message` 到文档记录，便于排查

---

## 4. 工作流执行引擎

### 4.1 DAG构建与拓扑排序

```python
# app/services/workflow_engine.py
from collections import deque

class WorkflowEngine:
    def __init__(self, workflow_id: int, db: Session):
        self.workflow_id = workflow_id
        self.db = db
        self.nodes: dict = {}
        self.edges: list = []
        self._load_workflow()

    def _load_workflow(self):
        nodes = self.db.query(WorkflowNode).filter(WorkflowNode.workflow_id == self.workflow_id).all()
        edges = self.db.query(WorkflowEdge).filter(WorkflowEdge.workflow_id == self.workflow_id).all()
        self.nodes = {n.id: n for n in nodes}
        self.edges = edges

    def _build_dag(self) -> list[list[int]]:
        """构建邻接表"""
        graph = {nid: [] for nid in self.nodes}
        in_degree = {nid: 0 for nid in self.nodes}
        for edge in self.edges:
            graph[edge.source_id].append(edge)
            in_degree[edge.target_id] += 1
        return graph, in_degree

    def _topological_sort(self) -> list[int]:
        """拓扑排序，返回执行顺序"""
        graph, in_degree = self._build_dag()
        queue = deque([nid for nid, deg in in_degree.items() if deg == 0])
        order = []
        while queue:
            nid = queue.popleft()
            order.append(nid)
            for edge in graph[nid]:
                in_degree[edge.target_id] -= 1
                if in_degree[edge.target_id] == 0:
                    queue.append(edge.target_id)
        return order

    async def execute(self, inputs: dict, stream: bool = False):
        """执行工作流"""
        order = self._topological_sort()
        context = {"inputs": inputs}
        execution = WorkflowExecution(
            workflow_id=self.workflow_id,
            status="running",
            inputs=inputs,
        )
        self.db.add(execution)
        self.db.commit()

        try:
            for node_id in order:
                node = self.nodes[node_id]
                result = await self._execute_node(node, context, stream)
                context[node_id] = result

            execution.status = "success"
            execution.outputs = context
        except Exception as e:
            execution.status = "failed"
            execution.error_message = str(e)
        finally:
            self.db.commit()

        return execution
```

### 4.2 节点执行器分发

```python
# app/services/workflow_engine.py (续)
async def _execute_node(self, node: WorkflowNode, context: dict, stream: bool = False):
    node_type = node.node_type

    if node_type == "start":
        return context.get("inputs", {})

    elif node_type == "end":
        return context.get("inputs", {})

    elif node_type == "llm":
        return await self._execute_llm_node(node, context, stream)

    elif node_type == "condition":
        return await self._execute_condition_node(node, context)

    elif node_type == "knowledge":
        return await self._execute_knowledge_node(node, context)

    elif node_type == "code":
        return await self._execute_code_node(node, context)

    elif node_type == "tool":
        return await self._execute_tool_node(node, context)

    elif node_type == "loop":
        return await self._execute_loop_node(node, context, stream)

    else:
        raise ValueError(f"Unsupported node type: {node_type}")
```

---

## 5. Agent执行流程

### 5.1 LangChain Agent构建

```python
# app/services/agent.py
from langchain.agents import AgentExecutor, create_react_agent
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain.memory import ConversationBufferWindowMemory

class AgentService:
    def __init__(self, agent_model, db: Session):
        self.agent = agent_model
        self.db = db
        self.llm_client: LLMClient = self._build_llm()
        self.tools: list = self._build_tools()

    def _build_llm(self) -> LLMClient:
        provider = self.db.query(AIProvider).join(AIModel, AIModel.provider_id == AIProvider.id).filter(AIModel.id == self.agent.model_id).first()
        model = self.db.query(AIModel).filter(AIModel.id == self.agent.model_id).first()
        return LLMClient(provider, model)

    def _build_tools(self) -> list:
        """根据agent_tools配置构建LangChain Tool列表"""
        agent_tools = self.db.query(AgentTool).filter(AgentTool.agent_id == self.agent.id, AgentTool.enabled == True).all()
        tools = []
        for tool in agent_tools:
            if tool.tool_type == "function":
                tools.append(self._build_function_tool(tool))
            elif tool.tool_type == "knowledge":
                tools.append(self._build_knowledge_tool(tool))
            elif tool.tool_type == "api":
                tools.append(self._build_api_tool(tool))
            elif tool.tool_type == "workflow":
                tools.append(self._build_workflow_tool(tool))
            elif tool.tool_type == "plugin":
                tools.append(self._build_plugin_tool(tool))
        return tools

    async def chat(self, conversation_id: int, user_message: str, stream: bool = True):
        """Agent对话入口"""
        # 加载历史消息
        history = self._load_history(conversation_id)

        # 构建prompt
        prompt = ChatPromptTemplate.from_messages([
            ("system", self.agent.system_prompt),
            MessagesPlaceholder("chat_history"),
            ("human", "{input}"),
            MessagesPlaceholder("agent_scratchpad"),
        ])

        # 创建Agent
        agent = create_react_agent(self.llm_client.chain, self.tools, prompt)
        executor = AgentExecutor(
            agent=agent,
            tools=self.tools,
            memory=ConversationBufferWindowMemory(
                chat_memory=history,
                return_messages=True,
                k=10,
            ),
            verbose=True,
            max_iterations=5,
        )

        if stream:
            return executor.ainvoke({"input": user_message})
        else:
            return executor.invoke({"input": user_message})
```

### 5.2 SSE流式响应

```python
# app/api/agent.py (流式端点)
from sse_starlette.sse import EventSourceResponse

@router.post("/{agent_id}/chat")
async def chat_stream(agent_id: int, request: ChatRequest, db: Session = Depends(get_session)):
    agent_service = AgentService(agent_id, db)

    async def event_generator():
        async for chunk in agent_service.chat_stream(request.conversation_id, request.message):
            yield {"data": json.dumps({"content": chunk.content, "role": "assistant"})}
        yield {"data": json.dumps({"done": True})}

    return EventSourceResponse(event_generator())
```

### 5.3 工具类型实现

```python
# 不同工具类型的构建方法

def _build_knowledge_tool(self, tool: AgentTool) -> Tool:
    """知识库检索工具"""
    kb_id = tool.config.get("knowledge_base_id")

    async def search_knowledge(query: str) -> str:
        embedding_client = self._get_embedding_client()
        query_embedding = await embedding_client.embed_query(query)
        results = await search_knowledge(kb_id, query, query_embedding)
        return "\n".join([r.content for r in results])

    return Tool(
        name=tool.name,
        description=tool.description,
        func=search_knowledge,
        coroutine=search_knowledge,
    )

def _build_api_tool(self, tool: AgentTool) -> Tool:
    """API调用工具"""
    import httpx

    async def call_api(params: str) -> str:
        config = tool.config
        async with httpx.AsyncClient() as client:
            response = await client.request(
                method=config.get("method", "GET"),
                url=config["url"],
                json=json.loads(params),
                headers=config.get("headers", {}),
                timeout=30,
            )
            return response.text

    return Tool(
        name=tool.name,
        description=tool.description,
        func=call_api,
        coroutine=call_api,
    )
```

---

## 6. 异常处理体系

```python
# app/core/exceptions.py
from fastapi import HTTPException

class AppException(HTTPException):
    def __init__(self, status_code: int, error_code: str, message: str):
        self.error_code = error_code
        self.message = message
        super().__init__(status_code=status_code, detail=message)

class NotFoundException(AppException):
    def __init__(self, resource: str, resource_id: int = None):
        msg = f"{resource} not found" + (f" (id={resource_id})" if resource_id else "")
        super().__init__(404, "NOT_FOUND", msg)

class UnauthorizedException(AppException):
    def __init__(self, message: str = "Unauthorized"):
        super().__init__(401, "UNAUTHORIZED", message)

class ForbiddenException(AppException):
    def __init__(self, resource: str = "", action: str = ""):
        msg = f"Permission denied: {action} on {resource}" if resource else "Permission denied"
        super().__init__(403, "FORBIDDEN", msg)

class ValidationException(AppException):
    def __init__(self, message: str):
        super().__init__(422, "VALIDATION_ERROR", message)

class QuotaExceededException(AppException):
    def __init__(self, resource: str):
        super().__init__(429, "QUOTA_EXCEEDED", f"Quota exceeded for {resource}")

class LLMException(AppException):
    def __init__(self, message: str):
        super().__init__(502, "LLM_ERROR", message)
```

## 7. 配置扩展

```python
# app/core/config.py 扩展项
class Config(BaseSettings):
    # MySQL (已有)
    database_type: str = 'mysql'
    connector: str = 'pymysql'
    database_host: str = 'localhost'
    database_port: int = 3306
    database_name: str = ''
    database_username: str = ''
    database_password: SecretStr = SecretStr('')

    # Qdrant (新增)
    qdrant_url: str = 'http://localhost:6333'
    qdrant_api_key: str = ''   # 本地部署可留空，云端部署时填写

    # Redis (新增)
    redis_host: str = 'localhost'
    redis_port: int = 6379
    redis_password: SecretStr = SecretStr('')
    redis_db: int = 0

    # JWT (新增)
    jwt_secret_key: SecretStr = SecretStr('change-me-in-production')
    jwt_algorithm: str = 'HS256'
    jwt_access_token_expire_minutes: int = 30
    jwt_refresh_token_expire_days: int = 7

    # Encryption (新增)
    fernet_key: SecretStr = SecretStr('')

    # File Upload (新增)
    upload_dir: str = '/tmp/ai_studio/uploads'
    max_upload_size_mb: int = 50

    # Celery (新增)
    celery_broker_url: str = 'redis://localhost:6379/1'
    celery_result_backend: str = 'redis://localhost:6379/2'

    model_config = {'env_file': str(BASE_DIR / '.env')}
```