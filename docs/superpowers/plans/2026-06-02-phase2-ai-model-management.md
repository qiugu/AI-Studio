# Phase 2: AI 模型管理 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 AI 供应商（AIProvider）和 AI 模型（AIModel）的完整 CRUD 管理，集成 LangChain 动态构建 ChatModel，提供供应商连通性测试和模型调用测试。

**Architecture:** 后端遵循 Phase 1 的分层模式（Model → Service → API），新增 `utils/encryption.py`（Fernet 加密）和 `utils/llm.py`（LangChain 封装）。前端新增 `types/ai-model.ts`、`api/ai-model.ts`，以及 `pages/AIModels/` 下的四个页面组件。路由注册到 `App.tsx`，`main.py` 注册新路由。

**Tech Stack:** Python 3.11 / FastAPI / SQLAlchemy 2.0 / Pydantic v2 / LangChain 0.3 / cryptography(Fernet) / React 19 / Ant Design 5 / TypeScript / axios

---

## 文件映射

**新建（后端）：**
- `backend/app/models/ai_provider.py` — AIProvider ORM 模型
- `backend/app/models/ai_model.py` — AIModel ORM 模型
- `backend/app/schemas/ai_provider.py` — 供应商 Pydantic schemas
- `backend/app/schemas/ai_model.py` — 模型 Pydantic schemas
- `backend/app/utils/encryption.py` — Fernet 加密工具
- `backend/app/utils/llm.py` — LangChain ChatModel 构建器
- `backend/app/services/ai_provider.py` — 供应商业务逻辑
- `backend/app/services/ai_model.py` — 模型业务逻辑
- `backend/app/api/ai_provider.py` — 供应商 API 路由
- `backend/app/api/ai_model.py` — 模型 API 路由
- `backend/tests/__init__.py` — 测试包
- `backend/tests/test_encryption.py` — 加密工具单元测试

**修改（后端）：**
- `backend/app/models/__init__.py` — 注册新模型
- `backend/app/services/quota.py` — 修复 check_model_quota()
- `backend/app/main.py` — 注册新路由
- `backend/requirements.txt` — 添加 LangChain 依赖
- `backend/.env` — 添加 FERNET_KEY

**新建（前端）：**
- `frontend/src/types/ai-model.ts` — TypeScript 接口
- `frontend/src/api/ai-model.ts` — axios API 层
- `frontend/src/pages/AIModels/ProviderList.tsx` — 供应商卡片列表
- `frontend/src/pages/AIModels/ProviderForm.tsx` — 供应商创建/编辑表单
- `frontend/src/pages/AIModels/ModelList.tsx` — 模型表格
- `frontend/src/pages/AIModels/ModelForm.tsx` — 模型创建/编辑表单
- `frontend/src/pages/AIModels/ConnectionTestModal.tsx` — 连接测试弹窗

**修改（前端）：**
- `frontend/src/App.tsx` — 注册新路由

---

## Task 1: 安装依赖 + 生成 Fernet Key

**Files:**
- Modify: `backend/requirements.txt`
- Modify: `backend/.env`

- [ ] **Step 1: 添加 LangChain 依赖到 requirements.txt**

在 `backend/requirements.txt` 末尾追加：

```
langchain==0.3.21
langchain-openai==0.3.11
langchain-anthropic==0.3.1
langchain-community==0.3.20
```

- [ ] **Step 2: 安装依赖**

```bash
cd backend && .venv/bin/pip install langchain==0.3.21 langchain-openai==0.3.11 langchain-anthropic==0.3.1 langchain-community==0.3.20
```

预期：安装完成，无报错。

- [ ] **Step 3: 生成 Fernet Key 并写入 .env**

```bash
cd backend && .venv/bin/python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

将输出的 key（形如 `abc123...=`）添加到 `backend/.env`：

```
# Encryption
fernet_key=<上面生成的key>
```

- [ ] **Step 4: 验证 Fernet key 可读**

```bash
cd backend && .venv/bin/python -c "
from app.core.config import config
k = config.fernet_key.get_secret_value()
print('Key length:', len(k))
assert len(k) == 44, 'Invalid Fernet key length'
print('OK')
"
```

预期输出：`Key length: 44` 和 `OK`

---

## Task 2: `app/utils/encryption.py` — Fernet 加密工具

**Files:**
- Create: `backend/app/utils/encryption.py`
- Create: `backend/tests/__init__.py`
- Create: `backend/tests/test_encryption.py`

- [ ] **Step 1: 写失败的测试**

新建 `backend/tests/__init__.py`（空文件）

新建 `backend/tests/test_encryption.py`：

```python
import os
import pytest
from cryptography.fernet import Fernet

# 测试用 key（不依赖 .env）
TEST_KEY = Fernet.generate_key().decode()


def test_encrypt_decrypt_roundtrip(monkeypatch):
    monkeypatch.setenv("FERNET_KEY", TEST_KEY)
    # 重新加载模块以应用 monkeypatch（使用直接 Fernet 测试）
    from cryptography.fernet import Fernet as F
    f = F(TEST_KEY.encode())
    plaintext = "sk-test-api-key-12345"
    encrypted = f.encrypt(plaintext.encode()).decode()
    decrypted = f.decrypt(encrypted.encode()).decode()
    assert decrypted == plaintext


def test_encrypt_produces_different_output_each_time():
    from cryptography.fernet import Fernet as F
    f = F(Fernet.generate_key())
    plaintext = "same-input"
    enc1 = f.encrypt(plaintext.encode())
    enc2 = f.encrypt(plaintext.encode())
    # Fernet 每次加密结果不同（包含随机 IV）
    assert enc1 != enc2


def test_decrypt_wrong_key_raises():
    from cryptography.fernet import Fernet as F, InvalidToken
    key1 = Fernet.generate_key()
    key2 = Fernet.generate_key()
    encrypted = F(key1).encrypt(b"secret")
    with pytest.raises(InvalidToken):
        F(key2).decrypt(encrypted)
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd backend && .venv/bin/pytest tests/test_encryption.py -v
```

预期：测试通过（这些测试直接使用 `cryptography`，不依赖我们自己的模块，所以这步其实是验证测试能运行）。

- [ ] **Step 3: 实现 encryption.py**

新建 `backend/app/utils/encryption.py`：

```python
from cryptography.fernet import Fernet
from app.core.config import config


def _get_fernet() -> Fernet:
    key = config.fernet_key.get_secret_value()
    if not key:
        raise RuntimeError("FERNET_KEY is not configured")
    return Fernet(key.encode())


def encrypt(plaintext: str) -> str:
    """加密明文字符串，返回 base64 编码的密文。"""
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """解密密文字符串，返回明文。"""
    return _get_fernet().decrypt(ciphertext.encode()).decode()
```

- [ ] **Step 4: 为 encryption.py 补充集成测试并运行**

在 `backend/tests/test_encryption.py` 末尾追加：

```python
def test_app_encrypt_decrypt(monkeypatch):
    """集成测试：通过 app.utils.encryption 加解密"""
    monkeypatch.setenv("FERNET_KEY", TEST_KEY)
    # 先设置 config，再导入模块
    import importlib
    import app.core.config as cfg_module
    original_key = cfg_module.config.fernet_key
    from pydantic import SecretStr
    cfg_module.config.fernet_key = SecretStr(TEST_KEY)

    from app.utils import encryption
    importlib.reload(encryption)

    plaintext = "my-secret-api-key"
    encrypted = encryption.encrypt(plaintext)
    assert encrypted != plaintext
    assert encryption.decrypt(encrypted) == plaintext

    # 恢复
    cfg_module.config.fernet_key = original_key
```

```bash
cd backend && .venv/bin/pytest tests/test_encryption.py -v
```

预期：所有测试 PASS。

- [ ] **Step 5: Commit**

```bash
cd backend && git add app/utils/encryption.py tests/ requirements.txt .env
git commit -m "feat(phase2): add Fernet encryption utility and LangChain deps"
```

---

## Task 3: `app/models/ai_provider.py` + `app/models/ai_model.py`

**Files:**
- Create: `backend/app/models/ai_provider.py`
- Create: `backend/app/models/ai_model.py`
- Modify: `backend/app/models/__init__.py`

- [ ] **Step 1: 创建 ai_provider.py**

新建 `backend/app/models/ai_provider.py`：

```python
from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, String, Text, JSON, Boolean, DateTime, func
from sqlalchemy.orm import mapped_column, Mapped

from app.core.database import Base


class AIProvider(Base):
    __tablename__ = "ai_providers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(50), nullable=False)
    api_base_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    api_key_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    config: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    status: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
```

- [ ] **Step 2: 创建 ai_model.py**

新建 `backend/app/models/ai_model.py`：

```python
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import BigInteger, String, JSON, Boolean, DateTime, func, Integer, Numeric
from sqlalchemy.orm import mapped_column, Mapped

from app.core.database import Base


class AIModel(Base):
    __tablename__ = "ai_models"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # tenant_id 为 NULL 表示平台预置公共模型
    tenant_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, index=True)
    provider_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    model_type: Mapped[str] = mapped_column(String(50), nullable=False)
    config: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    unit_price_input: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 6), nullable=True
    )
    unit_price_output: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 6), nullable=True
    )
    max_context_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    max_output_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
```

- [ ] **Step 3: 更新 `app/models/__init__.py`**

```python
from app.models.tenant import Tenant
from app.models.user import User
from app.models.role import Role
from app.models.permission import Permission
from app.models.user_role import user_role
from app.models.role_permission import role_permission
from app.models.api_key import ApiKey
from app.models.ai_provider import AIProvider
from app.models.ai_model import AIModel

__all__ = [
    "Tenant",
    "User",
    "Role",
    "Permission",
    "user_role",
    "role_permission",
    "ApiKey",
    "AIProvider",
    "AIModel",
]
```

- [ ] **Step 4: 验证模型导入无误**

```bash
cd backend && .venv/bin/python -c "from app.models import AIProvider, AIModel; print('OK')"
```

预期：输出 `OK`，无报错。

- [ ] **Step 5: Commit**

```bash
cd backend && git add app/models/ai_provider.py app/models/ai_model.py app/models/__init__.py
git commit -m "feat(phase2): add AIProvider and AIModel SQLAlchemy models"
```

---

## Task 4: Alembic 迁移

**Files:**
- Create: `backend/alembic/versions/<hash>_phase2_add_ai_providers_ai_models.py`（自动生成）

- [ ] **Step 1: 生成迁移脚本**

```bash
cd backend && .venv/bin/alembic revision --autogenerate -m "phase2_add_ai_providers_ai_models"
```

预期：在 `alembic/versions/` 下生成新文件，内含 `ai_providers` 和 `ai_models` 两张表的 `CREATE TABLE`。

- [ ] **Step 2: 检查迁移脚本**

打开生成的文件，确认：
- `upgrade()` 中有 `op.create_table('ai_providers', ...)` 和 `op.create_table('ai_models', ...)`
- 字段类型与模型定义一致（`TEXT` for `api_key_encrypted`，`NUMERIC(10,6)` for price 字段）
- `downgrade()` 中有对应 `op.drop_table`

- [ ] **Step 3: 运行迁移**

```bash
cd backend && .venv/bin/alembic upgrade head
```

预期：输出类似 `Running upgrade <prev> -> <new>, phase2_add_ai_providers_ai_models`，无报错。

- [ ] **Step 4: 验证表已创建**

```bash
cd backend && .venv/bin/python -c "
from app.core.database import engine
from sqlalchemy import inspect
inspector = inspect(engine)
tables = inspector.get_table_names()
assert 'ai_providers' in tables, 'ai_providers table not found'
assert 'ai_models' in tables, 'ai_models table not found'
print('Tables OK:', [t for t in tables if t.startswith('ai_')])
"
```

预期：打印包含 `ai_providers` 和 `ai_models` 的列表。

- [ ] **Step 5: Commit**

```bash
cd backend && git add alembic/versions/
git commit -m "feat(phase2): add Alembic migration for ai_providers and ai_models"
```

---

## Task 5: `app/schemas/ai_provider.py` + `app/schemas/ai_model.py`

**Files:**
- Create: `backend/app/schemas/ai_provider.py`
- Create: `backend/app/schemas/ai_model.py`

- [ ] **Step 1: 创建 `app/schemas/ai_provider.py`**

```python
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class AIProviderCreate(BaseModel):
    name: str = Field(..., max_length=255)
    provider_type: str = Field(..., max_length=50)
    api_base_url: Optional[str] = Field(None, max_length=500)
    # api_key 是明文，服务层加密存储；响应中不返回
    api_key: Optional[str] = None
    config: Optional[dict] = None
    status: bool = True


class AIProviderUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    provider_type: Optional[str] = Field(None, max_length=50)
    api_base_url: Optional[str] = Field(None, max_length=500)
    api_key: Optional[str] = None
    config: Optional[dict] = None
    status: Optional[bool] = None


class AIProviderOut(BaseModel):
    id: int
    tenant_id: int
    name: str
    provider_type: str
    api_base_url: Optional[str]
    # 不返回解密后的 api_key，仅告知是否已配置
    has_api_key: bool
    config: Optional[dict]
    status: bool
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_with_key_flag(cls, obj) -> "AIProviderOut":
        return cls(
            id=obj.id,
            tenant_id=obj.tenant_id,
            name=obj.name,
            provider_type=obj.provider_type,
            api_base_url=obj.api_base_url,
            has_api_key=bool(obj.api_key_encrypted),
            config=obj.config,
            status=obj.status,
            created_at=obj.created_at,
            updated_at=obj.updated_at,
        )


class ConnectivityTestRequest(BaseModel):
    model_name: str = Field(..., description="用于测试的模型名称，如 gpt-4o-mini")


class ConnectivityTestResult(BaseModel):
    success: bool
    latency_ms: Optional[int] = None
    error: Optional[str] = None
```

- [ ] **Step 2: 创建 `app/schemas/ai_model.py`**

```python
from datetime import datetime
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel, Field


class AIModelCreate(BaseModel):
    provider_id: int
    name: str = Field(..., max_length=255, description="模型标识，如 gpt-4o")
    display_name: str = Field(..., max_length=255)
    model_type: str = Field(..., max_length=50, description="chat/embedding/image/audio/rerank")
    config: Optional[dict] = None
    unit_price_input: Optional[Decimal] = None
    unit_price_output: Optional[Decimal] = None
    max_context_tokens: Optional[int] = None
    max_output_tokens: Optional[int] = None
    status: bool = True


class AIModelUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    display_name: Optional[str] = Field(None, max_length=255)
    model_type: Optional[str] = Field(None, max_length=50)
    config: Optional[dict] = None
    unit_price_input: Optional[Decimal] = None
    unit_price_output: Optional[Decimal] = None
    max_context_tokens: Optional[int] = None
    max_output_tokens: Optional[int] = None
    status: Optional[bool] = None


class AIModelOut(BaseModel):
    id: int
    tenant_id: Optional[int]
    provider_id: int
    name: str
    display_name: str
    model_type: str
    config: Optional[dict]
    unit_price_input: Optional[Decimal]
    unit_price_output: Optional[Decimal]
    max_context_tokens: Optional[int]
    max_output_tokens: Optional[int]
    status: bool
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    model_config = {"from_attributes": True}


class ModelTestRequest(BaseModel):
    messages: list[dict] = Field(
        ...,
        description="消息列表，格式: [{role: 'user', content: '...'}]"
    )


class ModelTestResult(BaseModel):
    content: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int
```

- [ ] **Step 3: 验证 schemas 导入**

```bash
cd backend && .venv/bin/python -c "
from app.schemas.ai_provider import AIProviderCreate, AIProviderOut, ConnectivityTestRequest
from app.schemas.ai_model import AIModelCreate, AIModelOut, ModelTestRequest
print('Schemas OK')
"
```

预期：输出 `Schemas OK`。

- [ ] **Step 4: Commit**

```bash
cd backend && git add app/schemas/ai_provider.py app/schemas/ai_model.py
git commit -m "feat(phase2): add Pydantic schemas for AIProvider and AIModel"
```

---

## Task 6: `app/utils/llm.py` — LangChain 动态 ChatModel 构建器

**Files:**
- Create: `backend/app/utils/llm.py`

- [ ] **Step 1: 实现 llm.py**

新建 `backend/app/utils/llm.py`：

```python
"""
LangChain LLM 客户端封装。
根据供应商类型动态构建 BaseChatModel。
"""
import time
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage

from app.core.exceptions import LLMException


def build_chat_model(
    provider_type: str,
    api_key: str,
    api_base_url: str | None = None,
    model_name: str = "gpt-4o-mini",
    **overrides: Any,
) -> BaseChatModel:
    """
    根据 provider_type 动态构建 LangChain BaseChatModel。

    支持：openai / anthropic / azure / ollama / custom（OpenAI 兼容模式）
    """
    kwargs: dict[str, Any] = {**overrides}

    if provider_type == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model_name,
            api_key=api_key,
            base_url=api_base_url,
            **kwargs,
        )

    elif provider_type == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model=model_name,
            api_key=api_key,
            **kwargs,
        )

    elif provider_type == "azure":
        from langchain_openai import AzureChatOpenAI
        # Azure 需要 api_base_url 作为 azure_endpoint
        return AzureChatOpenAI(
            azure_deployment=model_name,
            api_key=api_key,
            azure_endpoint=api_base_url or "",
            api_version=kwargs.pop("api_version", "2024-02-01"),
            **kwargs,
        )

    elif provider_type == "ollama":
        from langchain_community.chat_models import ChatOllama
        return ChatOllama(
            model=model_name,
            base_url=api_base_url or "http://localhost:11434",
            **kwargs,
        )

    else:
        # zhipu / baichuan / custom — 通常兼容 OpenAI API
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model_name,
            api_key=api_key,
            base_url=api_base_url,
            **kwargs,
        )


def test_connectivity(
    provider_type: str,
    api_key: str,
    api_base_url: str | None,
    model_name: str,
) -> dict:
    """
    测试供应商连通性。
    策略：优先发送简单消息（1 token），捕获任何认证/网络错误。
    返回: {"success": bool, "latency_ms": int | None, "error": str | None}
    """
    start = time.monotonic()
    try:
        llm = build_chat_model(
            provider_type=provider_type,
            api_key=api_key,
            api_base_url=api_base_url,
            model_name=model_name,
            max_tokens=1,
            temperature=0,
        )
        llm.invoke([HumanMessage(content="hi")])
        latency_ms = int((time.monotonic() - start) * 1000)
        return {"success": True, "latency_ms": latency_ms, "error": None}
    except Exception as e:
        latency_ms = int((time.monotonic() - start) * 1000)
        return {"success": False, "latency_ms": latency_ms, "error": str(e)}


def invoke_model(
    provider_type: str,
    api_key: str,
    api_base_url: str | None,
    model_name: str,
    messages: list[dict],
) -> dict:
    """
    调用模型并返回内容和 token 使用情况。
    messages 格式: [{"role": "user", "content": "..."}]
    返回: {"content": str, "prompt_tokens": int, "completion_tokens": int, "latency_ms": int}
    """
    from langchain_core.messages import HumanMessage, SystemMessage, AIMessage

    def to_lc_message(msg: dict):
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "system":
            return SystemMessage(content=content)
        elif role == "assistant":
            return AIMessage(content=content)
        return HumanMessage(content=content)

    start = time.monotonic()
    try:
        llm = build_chat_model(
            provider_type=provider_type,
            api_key=api_key,
            api_base_url=api_base_url,
            model_name=model_name,
        )
        lc_messages = [to_lc_message(m) for m in messages]
        response = llm.invoke(lc_messages)
        latency_ms = int((time.monotonic() - start) * 1000)

        usage = getattr(response, "usage_metadata", None) or {}
        return {
            "content": response.content,
            "prompt_tokens": usage.get("input_tokens", 0),
            "completion_tokens": usage.get("output_tokens", 0),
            "latency_ms": latency_ms,
        }
    except Exception as e:
        raise LLMException(str(e))
```

- [ ] **Step 2: 验证 llm.py 导入无误**

```bash
cd backend && .venv/bin/python -c "from app.utils.llm import build_chat_model, test_connectivity, invoke_model; print('LLM utils OK')"
```

预期：输出 `LLM utils OK`。

- [ ] **Step 3: Commit**

```bash
cd backend && git add app/utils/llm.py
git commit -m "feat(phase2): add LangChain LLM client with dynamic provider support"
```

---

## Task 7: `app/services/ai_provider.py`

**Files:**
- Create: `backend/app/services/ai_provider.py`

- [ ] **Step 1: 实现 ai_provider.py 服务**

新建 `backend/app/services/ai_provider.py`：

```python
from sqlalchemy.orm import Session

from app.models.ai_provider import AIProvider
from app.models.ai_model import AIModel
from app.schemas.ai_provider import AIProviderCreate, AIProviderUpdate, ConnectivityTestResult
from app.core.exceptions import NotFoundException, ConflictException
from app.utils.encryption import encrypt, decrypt
from app.utils import llm as llm_utils


class AIProviderService:
    def __init__(self, db: Session, tenant_id: int):
        self.db = db
        self.tenant_id = tenant_id

    def _get_or_404(self, provider_id: int) -> AIProvider:
        provider = (
            self.db.query(AIProvider)
            .filter(
                AIProvider.id == provider_id,
                AIProvider.tenant_id == self.tenant_id,
            )
            .first()
        )
        if not provider:
            raise NotFoundException("AIProvider", provider_id)
        return provider

    def list(self, page: int = 1, page_size: int = 20, status: bool | None = None):
        query = self.db.query(AIProvider).filter(
            AIProvider.tenant_id == self.tenant_id
        )
        if status is not None:
            query = query.filter(AIProvider.status == status)
        total = query.count()
        items = query.offset((page - 1) * page_size).limit(page_size).all()
        return items, total

    def get(self, provider_id: int) -> AIProvider:
        return self._get_or_404(provider_id)

    def create(self, data: AIProviderCreate) -> AIProvider:
        provider = AIProvider(
            tenant_id=self.tenant_id,
            name=data.name,
            provider_type=data.provider_type,
            api_base_url=data.api_base_url,
            api_key_encrypted=encrypt(data.api_key) if data.api_key else None,
            config=data.config,
            status=data.status,
        )
        self.db.add(provider)
        self.db.flush()
        return provider

    def update(self, provider_id: int, data: AIProviderUpdate) -> AIProvider:
        provider = self._get_or_404(provider_id)
        if data.name is not None:
            provider.name = data.name
        if data.provider_type is not None:
            provider.provider_type = data.provider_type
        if data.api_base_url is not None:
            provider.api_base_url = data.api_base_url
        if data.api_key is not None:
            provider.api_key_encrypted = encrypt(data.api_key)
        if data.config is not None:
            provider.config = data.config
        if data.status is not None:
            provider.status = data.status
        self.db.flush()
        return provider

    def delete(self, provider_id: int) -> None:
        provider = self._get_or_404(provider_id)
        # 检查是否有模型依赖此供应商
        model_count = (
            self.db.query(AIModel)
            .filter(AIModel.provider_id == provider_id)
            .count()
        )
        if model_count > 0:
            raise ConflictException(
                f"Cannot delete provider: {model_count} model(s) are using it"
            )
        self.db.delete(provider)
        self.db.flush()

    def test_connectivity(
        self, provider_id: int, model_name: str
    ) -> ConnectivityTestResult:
        provider = self._get_or_404(provider_id)
        api_key = decrypt(provider.api_key_encrypted) if provider.api_key_encrypted else ""
        result = llm_utils.test_connectivity(
            provider_type=provider.provider_type,
            api_key=api_key,
            api_base_url=provider.api_base_url,
            model_name=model_name,
        )
        return ConnectivityTestResult(**result)
```

- [ ] **Step 2: 验证导入**

```bash
cd backend && .venv/bin/python -c "from app.services.ai_provider import AIProviderService; print('AIProviderService OK')"
```

预期：`AIProviderService OK`

- [ ] **Step 3: Commit**

```bash
cd backend && git add app/services/ai_provider.py
git commit -m "feat(phase2): add AIProviderService with CRUD and connectivity test"
```

---

## Task 8: `app/services/ai_model.py` + 修复 quota.py

**Files:**
- Create: `backend/app/services/ai_model.py`
- Modify: `backend/app/services/quota.py`

- [ ] **Step 1: 实现 ai_model.py 服务**

新建 `backend/app/services/ai_model.py`：

```python
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.ai_model import AIModel
from app.models.ai_provider import AIProvider
from app.schemas.ai_model import AIModelCreate, AIModelUpdate, ModelTestResult
from app.core.exceptions import NotFoundException
from app.services.quota import QuotaService
from app.utils import llm as llm_utils
from app.utils.encryption import decrypt


class AIModelService:
    def __init__(self, db: Session, tenant_id: int):
        self.db = db
        self.tenant_id = tenant_id

    def _base_filter(self, include_public: bool = False):
        if include_public:
            return or_(
                AIModel.tenant_id == self.tenant_id,
                AIModel.tenant_id.is_(None),
            )
        return AIModel.tenant_id == self.tenant_id

    def _get_or_404(self, model_id: int) -> AIModel:
        model = (
            self.db.query(AIModel)
            .filter(
                self._base_filter(include_public=True),
                AIModel.id == model_id,
            )
            .first()
        )
        if not model:
            raise NotFoundException("AIModel", model_id)
        return model

    def list(
        self,
        page: int = 1,
        page_size: int = 20,
        model_type: str | None = None,
        provider_id: int | None = None,
        include_public: bool = False,
    ):
        query = self.db.query(AIModel).filter(self._base_filter(include_public))
        if model_type:
            query = query.filter(AIModel.model_type == model_type)
        if provider_id:
            query = query.filter(AIModel.provider_id == provider_id)
        total = query.count()
        items = query.offset((page - 1) * page_size).limit(page_size).all()
        return items, total

    def get(self, model_id: int) -> AIModel:
        return self._get_or_404(model_id)

    def create(self, data: AIModelCreate) -> AIModel:
        # 配额检查
        QuotaService(self.db).check_model_quota(self.tenant_id)
        model = AIModel(
            tenant_id=self.tenant_id,
            provider_id=data.provider_id,
            name=data.name,
            display_name=data.display_name,
            model_type=data.model_type,
            config=data.config,
            unit_price_input=data.unit_price_input,
            unit_price_output=data.unit_price_output,
            max_context_tokens=data.max_context_tokens,
            max_output_tokens=data.max_output_tokens,
            status=data.status,
        )
        self.db.add(model)
        self.db.flush()
        return model

    def update(self, model_id: int, data: AIModelUpdate) -> AIModel:
        model = self._get_or_404(model_id)
        # 公共模型（tenant_id=None）不允许普通租户修改
        if model.tenant_id is None:
            from app.core.exceptions import ForbiddenException
            raise ForbiddenException("ai_model", "update")
        update_fields = data.model_dump(exclude_none=True)
        for key, value in update_fields.items():
            setattr(model, key, value)
        self.db.flush()
        return model

    def delete(self, model_id: int) -> None:
        model = self._get_or_404(model_id)
        if model.tenant_id is None:
            from app.core.exceptions import ForbiddenException
            raise ForbiddenException("ai_model", "delete")
        self.db.delete(model)
        self.db.flush()

    def test_model(self, model_id: int, messages: list[dict]) -> ModelTestResult:
        model = self._get_or_404(model_id)
        provider = (
            self.db.query(AIProvider)
            .filter(AIProvider.id == model.provider_id)
            .first()
        )
        if not provider:
            raise NotFoundException("AIProvider", model.provider_id)
        api_key = decrypt(provider.api_key_encrypted) if provider.api_key_encrypted else ""
        result = llm_utils.invoke_model(
            provider_type=provider.provider_type,
            api_key=api_key,
            api_base_url=provider.api_base_url,
            model_name=model.name,
            messages=messages,
        )
        return ModelTestResult(**result)
```

- [ ] **Step 2: 修复 `app/services/quota.py` 中的 check_model_quota**

将 `backend/app/services/quota.py` 的 `check_model_quota` 方法替换为：

```python
def check_model_quota(self, tenant_id: int) -> None:
    """
    检查 AI 模型配额。
    超出配额时抛出 QuotaExceededException（返回 429）。
    """
    tenant = self._get_tenant(tenant_id)
    from app.models.ai_model import AIModel
    current_count = (
        self.db.query(AIModel)
        .filter(AIModel.tenant_id == tenant_id)
        .count()
    )
    if current_count >= tenant.max_models:
        raise QuotaExceededException("models")
```

注意：只替换 `check_model_quota` 方法，文件其他部分保持不变。

- [ ] **Step 3: 验证导入**

```bash
cd backend && .venv/bin/python -c "
from app.services.ai_model import AIModelService
from app.services.quota import QuotaService
print('Services OK')
"
```

预期：`Services OK`

- [ ] **Step 4: Commit**

```bash
cd backend && git add app/services/ai_model.py app/services/quota.py
git commit -m "feat(phase2): add AIModelService and fix QuotaService.check_model_quota"
```

---

## Task 9: `app/api/ai_provider.py` + `app/api/ai_model.py` + 注册路由

**Files:**
- Create: `backend/app/api/ai_provider.py`
- Create: `backend/app/api/ai_model.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: 实现 `app/api/ai_provider.py`**

新建 `backend/app/api/ai_provider.py`：

```python
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.core.dependencies import CurrentUser, CurrentTenantId
from app.schemas.ai_provider import (
    AIProviderCreate,
    AIProviderUpdate,
    AIProviderOut,
    ConnectivityTestRequest,
    ConnectivityTestResult,
)
from app.schemas.common import ResponseBase, PaginatedData
from app.services.ai_provider import AIProviderService

router = APIRouter()


@router.get("", response_model=ResponseBase)
def list_providers(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: bool | None = Query(None),
    tenant_id: int = CurrentTenantId,
    db: Session = Depends(get_session),
    _current_user=CurrentUser,
):
    svc = AIProviderService(db, tenant_id)
    items, total = svc.list(page=page, page_size=page_size, status=status)
    return ResponseBase.ok(
        data=PaginatedData(
            items=[AIProviderOut.from_orm_with_key_flag(p) for p in items],
            total=total,
            page=page,
            page_size=page_size,
        ).model_dump()
    )


@router.post("", response_model=ResponseBase)
def create_provider(
    data: AIProviderCreate,
    tenant_id: int = CurrentTenantId,
    db: Session = Depends(get_session),
    _current_user=CurrentUser,
):
    svc = AIProviderService(db, tenant_id)
    provider = svc.create(data)
    db.commit()
    db.refresh(provider)
    return ResponseBase.ok(data=AIProviderOut.from_orm_with_key_flag(provider).model_dump())


@router.get("/{provider_id}", response_model=ResponseBase)
def get_provider(
    provider_id: int,
    tenant_id: int = CurrentTenantId,
    db: Session = Depends(get_session),
    _current_user=CurrentUser,
):
    svc = AIProviderService(db, tenant_id)
    provider = svc.get(provider_id)
    return ResponseBase.ok(data=AIProviderOut.from_orm_with_key_flag(provider).model_dump())


@router.put("/{provider_id}", response_model=ResponseBase)
def update_provider(
    provider_id: int,
    data: AIProviderUpdate,
    tenant_id: int = CurrentTenantId,
    db: Session = Depends(get_session),
    _current_user=CurrentUser,
):
    svc = AIProviderService(db, tenant_id)
    provider = svc.update(provider_id, data)
    db.commit()
    db.refresh(provider)
    return ResponseBase.ok(data=AIProviderOut.from_orm_with_key_flag(provider).model_dump())


@router.delete("/{provider_id}", response_model=ResponseBase)
def delete_provider(
    provider_id: int,
    tenant_id: int = CurrentTenantId,
    db: Session = Depends(get_session),
    _current_user=CurrentUser,
):
    svc = AIProviderService(db, tenant_id)
    svc.delete(provider_id)
    db.commit()
    return ResponseBase.ok()


@router.post("/{provider_id}/test", response_model=ResponseBase)
def test_provider_connectivity(
    provider_id: int,
    data: ConnectivityTestRequest,
    tenant_id: int = CurrentTenantId,
    db: Session = Depends(get_session),
    _current_user=CurrentUser,
):
    svc = AIProviderService(db, tenant_id)
    result = svc.test_connectivity(provider_id, data.model_name)
    return ResponseBase.ok(data=result.model_dump())
```

- [ ] **Step 2: 实现 `app/api/ai_model.py`**

新建 `backend/app/api/ai_model.py`：

```python
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.core.dependencies import CurrentUser, CurrentTenantId
from app.schemas.ai_model import (
    AIModelCreate,
    AIModelUpdate,
    AIModelOut,
    ModelTestRequest,
    ModelTestResult,
)
from app.schemas.common import ResponseBase, PaginatedData
from app.services.ai_model import AIModelService

router = APIRouter()


@router.get("", response_model=ResponseBase)
def list_models(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    model_type: str | None = Query(None),
    provider_id: int | None = Query(None),
    include_public: bool = Query(False),
    tenant_id: int = CurrentTenantId,
    db: Session = Depends(get_session),
    _current_user=CurrentUser,
):
    svc = AIModelService(db, tenant_id)
    items, total = svc.list(
        page=page,
        page_size=page_size,
        model_type=model_type,
        provider_id=provider_id,
        include_public=include_public,
    )
    return ResponseBase.ok(
        data=PaginatedData(
            items=[AIModelOut.model_validate(m) for m in items],
            total=total,
            page=page,
            page_size=page_size,
        ).model_dump()
    )


@router.post("", response_model=ResponseBase)
def create_model(
    data: AIModelCreate,
    tenant_id: int = CurrentTenantId,
    db: Session = Depends(get_session),
    _current_user=CurrentUser,
):
    svc = AIModelService(db, tenant_id)
    model = svc.create(data)
    db.commit()
    db.refresh(model)
    return ResponseBase.ok(data=AIModelOut.model_validate(model).model_dump())


@router.get("/{model_id}", response_model=ResponseBase)
def get_model(
    model_id: int,
    tenant_id: int = CurrentTenantId,
    db: Session = Depends(get_session),
    _current_user=CurrentUser,
):
    svc = AIModelService(db, tenant_id)
    model = svc.get(model_id)
    return ResponseBase.ok(data=AIModelOut.model_validate(model).model_dump())


@router.put("/{model_id}", response_model=ResponseBase)
def update_model(
    model_id: int,
    data: AIModelUpdate,
    tenant_id: int = CurrentTenantId,
    db: Session = Depends(get_session),
    _current_user=CurrentUser,
):
    svc = AIModelService(db, tenant_id)
    model = svc.update(model_id, data)
    db.commit()
    db.refresh(model)
    return ResponseBase.ok(data=AIModelOut.model_validate(model).model_dump())


@router.delete("/{model_id}", response_model=ResponseBase)
def delete_model(
    model_id: int,
    tenant_id: int = CurrentTenantId,
    db: Session = Depends(get_session),
    _current_user=CurrentUser,
):
    svc = AIModelService(db, tenant_id)
    svc.delete(model_id)
    db.commit()
    return ResponseBase.ok()


@router.post("/{model_id}/test", response_model=ResponseBase)
def test_model(
    model_id: int,
    data: ModelTestRequest,
    tenant_id: int = CurrentTenantId,
    db: Session = Depends(get_session),
    _current_user=CurrentUser,
):
    svc = AIModelService(db, tenant_id)
    result = svc.test_model(model_id, data.messages)
    return ResponseBase.ok(data=result.model_dump())
```

- [ ] **Step 3: 注册路由到 `app/main.py`**

在 `backend/app/main.py` 的路由注册区域，在 `auth_router` 行之后添加：

```python
from app.api.ai_provider import router as ai_provider_router
from app.api.ai_model import router as ai_model_router
```

（加到文件顶部的 import 区域）

在 `app.include_router(auth_router, prefix="/auth", tags=["认证"])` 之后追加：

```python
app.include_router(ai_provider_router, prefix="/providers", tags=["AI供应商"])
app.include_router(ai_model_router, prefix="/ai-models", tags=["AI模型"])
```

- [ ] **Step 4: 启动服务验证路由注册**

```bash
cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000 &
sleep 3
curl -s http://localhost:8000/api/docs | grep -c "providers\|ai-models" || true
curl -s http://localhost:8000/openapi.json | python3 -c "import sys,json; d=json.load(sys.stdin); paths=[p for p in d['paths'] if 'providers' in p or 'ai-models' in p]; print('Registered paths:', paths)"
pkill -f "uvicorn app.main"
```

预期：输出包含 `/providers` 和 `/ai-models` 的路径列表。

- [ ] **Step 5: Commit**

```bash
cd backend && git add app/api/ai_provider.py app/api/ai_model.py app/main.py
git commit -m "feat(phase2): add AI provider and model API routes"
```

---

## Task 10: 前端类型定义 `src/types/ai-model.ts`

**Files:**
- Create: `frontend/src/types/ai-model.ts`

- [ ] **Step 1: 创建类型文件**

新建 `frontend/src/types/ai-model.ts`：

```typescript
// ── AI 供应商 ──────────────────────────────────────────────────────────────

export type ProviderType =
  | 'openai'
  | 'anthropic'
  | 'azure'
  | 'zhipu'
  | 'baichuan'
  | 'ollama'
  | 'custom'

export interface AIProvider {
  id: number
  tenant_id: number
  name: string
  provider_type: ProviderType
  api_base_url: string | null
  has_api_key: boolean
  config: Record<string, unknown> | null
  status: boolean
  created_at: string | null
  updated_at: string | null
}

export interface AIProviderCreateRequest {
  name: string
  provider_type: ProviderType
  api_base_url?: string
  api_key?: string
  config?: Record<string, unknown>
  status?: boolean
}

export interface AIProviderUpdateRequest {
  name?: string
  provider_type?: ProviderType
  api_base_url?: string
  api_key?: string
  config?: Record<string, unknown>
  status?: boolean
}

export interface ConnectivityTestRequest {
  model_name: string
}

export interface ConnectivityTestResult {
  success: boolean
  latency_ms: number | null
  error: string | null
}

// ── AI 模型 ───────────────────────────────────────────────────────────────

export type ModelType = 'chat' | 'embedding' | 'image' | 'audio' | 'rerank'

export interface AIModel {
  id: number
  tenant_id: number | null
  provider_id: number
  name: string
  display_name: string
  model_type: ModelType
  config: Record<string, unknown> | null
  unit_price_input: string | null
  unit_price_output: string | null
  max_context_tokens: number | null
  max_output_tokens: number | null
  status: boolean
  created_at: string | null
  updated_at: string | null
}

export interface AIModelCreateRequest {
  provider_id: number
  name: string
  display_name: string
  model_type: ModelType
  config?: Record<string, unknown>
  unit_price_input?: string
  unit_price_output?: string
  max_context_tokens?: number
  max_output_tokens?: number
  status?: boolean
}

export interface AIModelUpdateRequest {
  name?: string
  display_name?: string
  model_type?: ModelType
  config?: Record<string, unknown>
  unit_price_input?: string
  unit_price_output?: string
  max_context_tokens?: number
  max_output_tokens?: number
  status?: boolean
}

export interface ModelTestRequest {
  messages: Array<{ role: 'user' | 'assistant' | 'system'; content: string }>
}

export interface ModelTestResult {
  content: string
  prompt_tokens: number
  completion_tokens: number
  latency_ms: number
}
```

- [ ] **Step 2: Commit**

```bash
cd frontend && git add src/types/ai-model.ts
git commit -m "feat(phase2): add TypeScript types for AIProvider and AIModel"
```

---

## Task 11: 前端 API 层 `src/api/ai-model.ts`

**Files:**
- Create: `frontend/src/api/ai-model.ts`

- [ ] **Step 1: 实现 API 层**

新建 `frontend/src/api/ai-model.ts`：

```typescript
import apiClient from './client'
import type { ApiResponse, PaginatedData, PageParams } from '@/types/api'
import type {
  AIProvider,
  AIProviderCreateRequest,
  AIProviderUpdateRequest,
  ConnectivityTestRequest,
  ConnectivityTestResult,
  AIModel,
  AIModelCreateRequest,
  AIModelUpdateRequest,
  ModelTestRequest,
  ModelTestResult,
} from '@/types/ai-model'

// ── 供应商 API ──────────────────────────────────────────────────────────────

export async function listProviders(
  params?: PageParams & { status?: boolean }
): Promise<ApiResponse<PaginatedData<AIProvider>>> {
  const response = await apiClient.get('/providers', { params })
  return response as unknown as ApiResponse<PaginatedData<AIProvider>>
}

export async function getProvider(id: number): Promise<ApiResponse<AIProvider>> {
  const response = await apiClient.get(`/providers/${id}`)
  return response as unknown as ApiResponse<AIProvider>
}

export async function createProvider(
  data: AIProviderCreateRequest
): Promise<ApiResponse<AIProvider>> {
  const response = await apiClient.post('/providers', data)
  return response as unknown as ApiResponse<AIProvider>
}

export async function updateProvider(
  id: number,
  data: AIProviderUpdateRequest
): Promise<ApiResponse<AIProvider>> {
  const response = await apiClient.put(`/providers/${id}`, data)
  return response as unknown as ApiResponse<AIProvider>
}

export async function deleteProvider(id: number): Promise<ApiResponse<null>> {
  const response = await apiClient.delete(`/providers/${id}`)
  return response as unknown as ApiResponse<null>
}

export async function testProviderConnectivity(
  id: number,
  data: ConnectivityTestRequest
): Promise<ApiResponse<ConnectivityTestResult>> {
  const response = await apiClient.post(`/providers/${id}/test`, data)
  return response as unknown as ApiResponse<ConnectivityTestResult>
}

// ── 模型 API ──────────────────────────────────────────────────────────────

export async function listModels(
  params?: PageParams & {
    model_type?: string
    provider_id?: number
    include_public?: boolean
  }
): Promise<ApiResponse<PaginatedData<AIModel>>> {
  const response = await apiClient.get('/ai-models', { params })
  return response as unknown as ApiResponse<PaginatedData<AIModel>>
}

export async function getModel(id: number): Promise<ApiResponse<AIModel>> {
  const response = await apiClient.get(`/ai-models/${id}`)
  return response as unknown as ApiResponse<AIModel>
}

export async function createModel(
  data: AIModelCreateRequest
): Promise<ApiResponse<AIModel>> {
  const response = await apiClient.post('/ai-models', data)
  return response as unknown as ApiResponse<AIModel>
}

export async function updateModel(
  id: number,
  data: AIModelUpdateRequest
): Promise<ApiResponse<AIModel>> {
  const response = await apiClient.put(`/ai-models/${id}`, data)
  return response as unknown as ApiResponse<AIModel>
}

export async function deleteModel(id: number): Promise<ApiResponse<null>> {
  const response = await apiClient.delete(`/ai-models/${id}`)
  return response as unknown as ApiResponse<null>
}

export async function testModel(
  id: number,
  data: ModelTestRequest
): Promise<ApiResponse<ModelTestResult>> {
  const response = await apiClient.post(`/ai-models/${id}/test`, data)
  return response as unknown as ApiResponse<ModelTestResult>
}
```

- [ ] **Step 2: Commit**

```bash
cd frontend && git add src/api/ai-model.ts
git commit -m "feat(phase2): add AI model API client"
```

---

## Task 12: `ConnectionTestModal.tsx` — 连接测试弹窗组件

**Files:**
- Create: `frontend/src/pages/AIModels/ConnectionTestModal.tsx`

- [ ] **Step 1: 创建弹窗组件**

新建 `frontend/src/pages/AIModels/ConnectionTestModal.tsx`：

```tsx
import { useState } from 'react'
import { Modal, Form, Input, Button, Alert, Spin, Space, Typography } from 'antd'
import { CheckCircleOutlined, CloseCircleOutlined } from '@ant-design/icons'
import { testProviderConnectivity } from '@/api/ai-model'
import type { ConnectivityTestResult } from '@/types/ai-model'

const { Text } = Typography

interface Props {
  open: boolean
  providerId: number
  onClose: () => void
}

export default function ConnectionTestModal({ open, providerId, onClose }: Props) {
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<ConnectivityTestResult | null>(null)

  const handleTest = async () => {
    const values = await form.validateFields()
    setLoading(true)
    setResult(null)
    try {
      const res = await testProviderConnectivity(providerId, { model_name: values.model_name })
      setResult(res.data)
    } catch {
      setResult({ success: false, latency_ms: null, error: '请求失败，请检查网络' })
    } finally {
      setLoading(false)
    }
  }

  const handleClose = () => {
    form.resetFields()
    setResult(null)
    onClose()
  }

  return (
    <Modal
      title="连接测试"
      open={open}
      onCancel={handleClose}
      footer={null}
      width={480}
    >
      <Form form={form} layout="vertical">
        <Form.Item
          name="model_name"
          label="测试模型"
          rules={[{ required: true, message: '请输入模型名称' }]}
          extra="如：gpt-4o-mini、claude-3-haiku-20240307"
        >
          <Input placeholder="输入模型名称" />
        </Form.Item>
        <Form.Item>
          <Button type="primary" onClick={handleTest} loading={loading} block>
            开始测试
          </Button>
        </Form.Item>
      </Form>

      {loading && (
        <div style={{ textAlign: 'center', padding: '16px 0' }}>
          <Spin tip="正在测试连接..." />
        </div>
      )}

      {result && !loading && (
        result.success ? (
          <Alert
            type="success"
            icon={<CheckCircleOutlined />}
            showIcon
            message="连接成功"
            description={
              <Space direction="vertical">
                <Text>供应商连接正常</Text>
                {result.latency_ms != null && (
                  <Text type="secondary">响应延迟: {result.latency_ms} ms</Text>
                )}
              </Space>
            }
          />
        ) : (
          <Alert
            type="error"
            icon={<CloseCircleOutlined />}
            showIcon
            message="连接失败"
            description={result.error || '未知错误'}
          />
        )
      )}
    </Modal>
  )
}
```

- [ ] **Step 2: Commit**

```bash
cd frontend && git add src/pages/AIModels/ConnectionTestModal.tsx
git commit -m "feat(phase2): add ConnectionTestModal component"
```

---

## Task 13: `ProviderList.tsx` + `ProviderForm.tsx`

**Files:**
- Create: `frontend/src/pages/AIModels/ProviderList.tsx`
- Create: `frontend/src/pages/AIModels/ProviderForm.tsx`

- [ ] **Step 1: 创建 `ProviderList.tsx`**

新建 `frontend/src/pages/AIModels/ProviderList.tsx`：

```tsx
import { useEffect, useState } from 'react'
import {
  Card,
  Row,
  Col,
  Button,
  Badge,
  Typography,
  Space,
  Popconfirm,
  message,
  Empty,
  Spin,
  Tag,
} from 'antd'
import {
  PlusOutlined,
  EditOutlined,
  DeleteOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { listProviders, deleteProvider } from '@/api/ai-model'
import type { AIProvider } from '@/types/ai-model'
import ConnectionTestModal from './ConnectionTestModal'

const { Title, Text } = Typography

const PROVIDER_LABELS: Record<string, string> = {
  openai: 'OpenAI',
  anthropic: 'Anthropic',
  azure: 'Azure OpenAI',
  zhipu: '智谱 AI',
  baichuan: '百川 AI',
  ollama: 'Ollama',
  custom: '自定义',
}

export default function ProviderList() {
  const navigate = useNavigate()
  const [providers, setProviders] = useState<AIProvider[]>([])
  const [loading, setLoading] = useState(true)
  const [testModal, setTestModal] = useState<{ open: boolean; providerId: number }>({
    open: false,
    providerId: 0,
  })

  const fetchProviders = async () => {
    setLoading(true)
    try {
      const res = await listProviders({ page: 1, page_size: 100 })
      setProviders(res.data?.items ?? [])
    } catch {
      message.error('加载供应商列表失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchProviders()
  }, [])

  const handleDelete = async (id: number) => {
    try {
      await deleteProvider(id)
      message.success('删除成功')
      fetchProviders()
    } catch (e: unknown) {
      const err = e as { response?: { data?: { message?: string } } }
      message.error(err?.response?.data?.message || '删除失败')
    }
  }

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: 48 }}>
        <Spin size="large" />
      </div>
    )
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 24 }}>
        <Title level={4} style={{ margin: 0 }}>AI 供应商管理</Title>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => navigate('/providers/new')}
        >
          新增供应商
        </Button>
      </div>

      {providers.length === 0 ? (
        <Empty description="暂无供应商，点击右上角添加" />
      ) : (
        <Row gutter={[16, 16]}>
          {providers.map((provider) => (
            <Col key={provider.id} xs={24} sm={12} lg={8} xl={6}>
              <Card
                hoverable
                actions={[
                  <ThunderboltOutlined
                    key="test"
                    title="连接测试"
                    onClick={() => setTestModal({ open: true, providerId: provider.id })}
                  />,
                  <EditOutlined
                    key="edit"
                    title="编辑"
                    onClick={() => navigate(`/providers/${provider.id}/edit`)}
                  />,
                  <Popconfirm
                    key="delete"
                    title="确认删除此供应商？"
                    description="删除后该供应商下的模型将无法使用"
                    onConfirm={() => handleDelete(provider.id)}
                    okText="删除"
                    okButtonProps={{ danger: true }}
                    cancelText="取消"
                  >
                    <DeleteOutlined title="删除" style={{ color: '#ff4d4f' }} />
                  </Popconfirm>,
                ]}
              >
                <Space direction="vertical" style={{ width: '100%' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <Text strong style={{ fontSize: 16 }}>{provider.name}</Text>
                    <Badge
                      status={provider.status ? 'success' : 'default'}
                      text={provider.status ? '启用' : '禁用'}
                    />
                  </div>
                  <Tag color="blue">{PROVIDER_LABELS[provider.provider_type] ?? provider.provider_type}</Tag>
                  {provider.api_base_url && (
                    <Text type="secondary" ellipsis style={{ fontSize: 12 }}>
                      {provider.api_base_url}
                    </Text>
                  )}
                  <Text type={provider.has_api_key ? 'success' : 'warning'} style={{ fontSize: 12 }}>
                    {provider.has_api_key ? 'API Key 已配置' : 'API Key 未配置'}
                  </Text>
                </Space>
              </Card>
            </Col>
          ))}
        </Row>
      )}

      <ConnectionTestModal
        open={testModal.open}
        providerId={testModal.providerId}
        onClose={() => setTestModal({ open: false, providerId: 0 })}
      />
    </div>
  )
}
```

- [ ] **Step 2: 创建 `ProviderForm.tsx`**

新建 `frontend/src/pages/AIModels/ProviderForm.tsx`：

```tsx
import { useEffect, useState } from 'react'
import {
  Form,
  Input,
  Select,
  Switch,
  Button,
  Card,
  Typography,
  Space,
  message,
} from 'antd'
import { useNavigate, useParams } from 'react-router-dom'
import { createProvider, getProvider, updateProvider } from '@/api/ai-model'
import type { AIProviderCreateRequest } from '@/types/ai-model'

const { Title } = Typography

const PROVIDER_TYPES = [
  { value: 'openai', label: 'OpenAI' },
  { value: 'anthropic', label: 'Anthropic' },
  { value: 'azure', label: 'Azure OpenAI' },
  { value: 'zhipu', label: '智谱 AI' },
  { value: 'baichuan', label: '百川 AI' },
  { value: 'ollama', label: 'Ollama（本地）' },
  { value: 'custom', label: '自定义（OpenAI 兼容）' },
]

export default function ProviderForm() {
  const navigate = useNavigate()
  const { id } = useParams<{ id: string }>()
  const isEdit = Boolean(id)
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [initializing, setInitializing] = useState(isEdit)

  useEffect(() => {
    if (!isEdit || !id) return
    getProvider(Number(id))
      .then((res) => {
        const p = res.data
        form.setFieldsValue({
          name: p.name,
          provider_type: p.provider_type,
          api_base_url: p.api_base_url,
          config: p.config ? JSON.stringify(p.config, null, 2) : '',
          status: p.status,
        })
      })
      .catch(() => message.error('加载供应商信息失败'))
      .finally(() => setInitializing(false))
  }, [id, isEdit, form])

  const handleSubmit = async (values: Record<string, unknown>) => {
    setLoading(true)
    try {
      const payload: AIProviderCreateRequest = {
        name: values.name as string,
        provider_type: values.provider_type as AIProviderCreateRequest['provider_type'],
        api_base_url: values.api_base_url as string | undefined,
        api_key: values.api_key as string | undefined,
        status: values.status as boolean,
      }
      if (values.config) {
        try {
          payload.config = JSON.parse(values.config as string)
        } catch {
          message.error('额外配置 JSON 格式错误')
          return
        }
      }

      if (isEdit && id) {
        await updateProvider(Number(id), payload)
        message.success('更新成功')
      } else {
        await createProvider(payload)
        message.success('创建成功')
      }
      navigate('/providers')
    } catch (e: unknown) {
      const err = e as { response?: { data?: { message?: string } } }
      message.error(err?.response?.data?.message || (isEdit ? '更新失败' : '创建失败'))
    } finally {
      setLoading(false)
    }
  }

  if (initializing) return null

  return (
    <div style={{ maxWidth: 640, margin: '0 auto' }}>
      <Title level={4}>{isEdit ? '编辑供应商' : '新增供应商'}</Title>
      <Card>
        <Form form={form} layout="vertical" onFinish={handleSubmit} initialValues={{ status: true }}>
          <Form.Item name="name" label="供应商名称" rules={[{ required: true }]}>
            <Input placeholder="如：我的 OpenAI" />
          </Form.Item>

          <Form.Item name="provider_type" label="供应商类型" rules={[{ required: true }]}>
            <Select options={PROVIDER_TYPES} placeholder="选择供应商类型" />
          </Form.Item>

          <Form.Item name="api_base_url" label="API Base URL">
            <Input placeholder="如：https://api.openai.com/v1（留空使用默认）" />
          </Form.Item>

          <Form.Item
            name="api_key"
            label={isEdit ? 'API Key（留空保持不变）' : 'API Key'}
            rules={isEdit ? [] : [{ required: true, message: '请输入 API Key' }]}
          >
            <Input.Password placeholder="sk-..." />
          </Form.Item>

          <Form.Item name="config" label="额外配置（JSON 格式，可选）">
            <Input.TextArea rows={3} placeholder='{"timeout": 30}' />
          </Form.Item>

          <Form.Item name="status" label="启用状态" valuePropName="checked">
            <Switch checkedChildren="启用" unCheckedChildren="禁用" />
          </Form.Item>

          <Form.Item>
            <Space>
              <Button type="primary" htmlType="submit" loading={loading}>
                {isEdit ? '保存修改' : '创建供应商'}
              </Button>
              <Button onClick={() => navigate('/providers')}>取消</Button>
            </Space>
          </Form.Item>
        </Form>
      </Card>
    </div>
  )
}
```

- [ ] **Step 3: Commit**

```bash
cd frontend && git add src/pages/AIModels/ProviderList.tsx src/pages/AIModels/ProviderForm.tsx
git commit -m "feat(phase2): add ProviderList and ProviderForm pages"
```

---

## Task 14: `ModelList.tsx` + `ModelForm.tsx`

**Files:**
- Create: `frontend/src/pages/AIModels/ModelList.tsx`
- Create: `frontend/src/pages/AIModels/ModelForm.tsx`

- [ ] **Step 1: 创建 `ModelList.tsx`**

新建 `frontend/src/pages/AIModels/ModelList.tsx`：

```tsx
import { useEffect, useState } from 'react'
import {
  Table,
  Button,
  Space,
  Tag,
  Switch,
  Popconfirm,
  message,
  Select,
  Typography,
  Badge,
  Tooltip,
} from 'antd'
import { PlusOutlined, EditOutlined, DeleteOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import type { ColumnsType } from 'antd/es/table'
import { listModels, deleteModel, listProviders } from '@/api/ai-model'
import type { AIModel, AIProvider, ModelType } from '@/types/ai-model'

const { Title } = Typography

const MODEL_TYPE_COLORS: Record<ModelType, string> = {
  chat: 'blue',
  embedding: 'green',
  image: 'purple',
  audio: 'orange',
  rerank: 'cyan',
}

export default function ModelList() {
  const navigate = useNavigate()
  const [models, setModels] = useState<AIModel[]>([])
  const [providers, setProviders] = useState<AIProvider[]>([])
  const [loading, setLoading] = useState(true)
  const [filters, setFilters] = useState<{
    model_type?: string
    provider_id?: number
    include_public: boolean
  }>({ include_public: false })

  const fetchAll = async () => {
    setLoading(true)
    try {
      const [modelsRes, providersRes] = await Promise.all([
        listModels({ page: 1, page_size: 200, ...filters }),
        listProviders({ page: 1, page_size: 100 }),
      ])
      setModels(modelsRes.data?.items ?? [])
      setProviders(providersRes.data?.items ?? [])
    } catch {
      message.error('加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchAll()
  }, [filters])

  const handleDelete = async (id: number) => {
    try {
      await deleteModel(id)
      message.success('删除成功')
      fetchAll()
    } catch (e: unknown) {
      const err = e as { response?: { data?: { message?: string } } }
      message.error(err?.response?.data?.message || '删除失败')
    }
  }

  const providerMap = Object.fromEntries(providers.map((p) => [p.id, p.name]))

  const columns: ColumnsType<AIModel> = [
    {
      title: '模型标识',
      dataIndex: 'name',
      key: 'name',
      render: (name, record) => (
        <Space>
          <span>{name}</span>
          {record.tenant_id === null && <Tag color="gold">公共</Tag>}
        </Space>
      ),
    },
    { title: '显示名称', dataIndex: 'display_name', key: 'display_name' },
    {
      title: '类型',
      dataIndex: 'model_type',
      key: 'model_type',
      render: (type: ModelType) => (
        <Tag color={MODEL_TYPE_COLORS[type] ?? 'default'}>{type}</Tag>
      ),
    },
    {
      title: '供应商',
      dataIndex: 'provider_id',
      key: 'provider_id',
      render: (id) => providerMap[id] ?? `Provider #${id}`,
    },
    {
      title: '输入价格',
      dataIndex: 'unit_price_input',
      key: 'unit_price_input',
      render: (price) => (price ? `$${price}/1K` : '—'),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (status) => (
        <Badge status={status ? 'success' : 'default'} text={status ? '启用' : '禁用'} />
      ),
    },
    {
      title: '操作',
      key: 'actions',
      render: (_, record) => {
        const isPublic = record.tenant_id === null
        return (
          <Space>
            <Tooltip title={isPublic ? '公共模型不可编辑' : '编辑'}>
              <Button
                size="small"
                icon={<EditOutlined />}
                disabled={isPublic}
                onClick={() => navigate(`/ai-models/${record.id}/edit`)}
              />
            </Tooltip>
            <Popconfirm
              title="确认删除此模型？"
              onConfirm={() => handleDelete(record.id)}
              okText="删除"
              okButtonProps={{ danger: true }}
              cancelText="取消"
              disabled={isPublic}
            >
              <Tooltip title={isPublic ? '公共模型不可删除' : '删除'}>
                <Button
                  size="small"
                  icon={<DeleteOutlined />}
                  danger
                  disabled={isPublic}
                />
              </Tooltip>
            </Popconfirm>
          </Space>
        )
      },
    },
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>AI 模型管理</Title>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => navigate('/ai-models/new')}
        >
          新增模型
        </Button>
      </div>

      <Space style={{ marginBottom: 16 }}>
        <Select
          placeholder="筛选类型"
          allowClear
          style={{ width: 140 }}
          options={[
            { value: 'chat', label: '对话' },
            { value: 'embedding', label: 'Embedding' },
            { value: 'image', label: '图像' },
            { value: 'audio', label: '音频' },
            { value: 'rerank', label: 'Rerank' },
          ]}
          onChange={(v) => setFilters((f) => ({ ...f, model_type: v }))}
        />
        <Select
          placeholder="筛选供应商"
          allowClear
          style={{ width: 180 }}
          options={providers.map((p) => ({ value: p.id, label: p.name }))}
          onChange={(v) => setFilters((f) => ({ ...f, provider_id: v }))}
        />
        <Space>
          <span>显示公共模型</span>
          <Switch
            checked={filters.include_public}
            onChange={(v) => setFilters((f) => ({ ...f, include_public: v }))}
          />
        </Space>
      </Space>

      <Table
        columns={columns}
        dataSource={models}
        rowKey="id"
        loading={loading}
        pagination={{ pageSize: 20 }}
      />
    </div>
  )
}
```

- [ ] **Step 2: 创建 `ModelForm.tsx`**

新建 `frontend/src/pages/AIModels/ModelForm.tsx`：

```tsx
import { useEffect, useState } from 'react'
import {
  Form,
  Input,
  Select,
  InputNumber,
  Switch,
  Button,
  Card,
  Typography,
  Space,
  message,
} from 'antd'
import { useNavigate, useParams } from 'react-router-dom'
import { createModel, getModel, updateModel, listProviders } from '@/api/ai-model'
import type { AIModelCreateRequest, AIProvider } from '@/types/ai-model'

const { Title } = Typography

const MODEL_TYPE_OPTIONS = [
  { value: 'chat', label: '对话（Chat）' },
  { value: 'embedding', label: 'Embedding' },
  { value: 'image', label: '图像生成' },
  { value: 'audio', label: '音频' },
  { value: 'rerank', label: 'Rerank' },
]

export default function ModelForm() {
  const navigate = useNavigate()
  const { id } = useParams<{ id: string }>()
  const isEdit = Boolean(id)
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [providers, setProviders] = useState<AIProvider[]>([])
  const [initializing, setInitializing] = useState(true)

  useEffect(() => {
    const init = async () => {
      try {
        const providersRes = await listProviders({ page: 1, page_size: 100 })
        setProviders(providersRes.data?.items ?? [])
        if (isEdit && id) {
          const modelRes = await getModel(Number(id))
          const m = modelRes.data
          form.setFieldsValue({
            provider_id: m.provider_id,
            name: m.name,
            display_name: m.display_name,
            model_type: m.model_type,
            unit_price_input: m.unit_price_input,
            unit_price_output: m.unit_price_output,
            max_context_tokens: m.max_context_tokens,
            max_output_tokens: m.max_output_tokens,
            status: m.status,
          })
        }
      } catch {
        message.error('初始化失败')
      } finally {
        setInitializing(false)
      }
    }
    init()
  }, [id, isEdit, form])

  const handleSubmit = async (values: Record<string, unknown>) => {
    setLoading(true)
    try {
      const payload: AIModelCreateRequest = {
        provider_id: values.provider_id as number,
        name: values.name as string,
        display_name: values.display_name as string,
        model_type: values.model_type as AIModelCreateRequest['model_type'],
        status: values.status as boolean,
        unit_price_input: values.unit_price_input as string | undefined,
        unit_price_output: values.unit_price_output as string | undefined,
        max_context_tokens: values.max_context_tokens as number | undefined,
        max_output_tokens: values.max_output_tokens as number | undefined,
      }
      if (isEdit && id) {
        await updateModel(Number(id), payload)
        message.success('更新成功')
      } else {
        await createModel(payload)
        message.success('创建成功')
      }
      navigate('/ai-models')
    } catch (e: unknown) {
      const err = e as { response?: { data?: { message?: string } } }
      message.error(err?.response?.data?.message || (isEdit ? '更新失败' : '创建失败'))
    } finally {
      setLoading(false)
    }
  }

  if (initializing) return null

  return (
    <div style={{ maxWidth: 640, margin: '0 auto' }}>
      <Title level={4}>{isEdit ? '编辑模型' : '新增模型'}</Title>
      <Card>
        <Form form={form} layout="vertical" onFinish={handleSubmit} initialValues={{ status: true }}>
          <Form.Item name="provider_id" label="所属供应商" rules={[{ required: true }]}>
            <Select
              placeholder="选择供应商"
              options={providers.map((p) => ({ value: p.id, label: p.name }))}
            />
          </Form.Item>

          <Form.Item name="name" label="模型标识" rules={[{ required: true }]}
            extra="如：gpt-4o、claude-3-5-sonnet-20241022">
            <Input placeholder="模型的 API 调用名称" />
          </Form.Item>

          <Form.Item name="display_name" label="显示名称" rules={[{ required: true }]}>
            <Input placeholder="如：GPT-4o" />
          </Form.Item>

          <Form.Item name="model_type" label="模型类型" rules={[{ required: true }]}>
            <Select options={MODEL_TYPE_OPTIONS} />
          </Form.Item>

          <Form.Item name="unit_price_input" label="输入单价（$/1K tokens）">
            <InputNumber style={{ width: '100%' }} min={0} step={0.000001} placeholder="0.000005" />
          </Form.Item>

          <Form.Item name="unit_price_output" label="输出单价（$/1K tokens）">
            <InputNumber style={{ width: '100%' }} min={0} step={0.000001} placeholder="0.000015" />
          </Form.Item>

          <Form.Item name="max_context_tokens" label="最大上下文 Token">
            <InputNumber style={{ width: '100%' }} min={1} placeholder="128000" />
          </Form.Item>

          <Form.Item name="max_output_tokens" label="最大输出 Token">
            <InputNumber style={{ width: '100%' }} min={1} placeholder="4096" />
          </Form.Item>

          <Form.Item name="status" label="启用状态" valuePropName="checked">
            <Switch checkedChildren="启用" unCheckedChildren="禁用" />
          </Form.Item>

          <Form.Item>
            <Space>
              <Button type="primary" htmlType="submit" loading={loading}>
                {isEdit ? '保存修改' : '创建模型'}
              </Button>
              <Button onClick={() => navigate('/ai-models')}>取消</Button>
            </Space>
          </Form.Item>
        </Form>
      </Card>
    </div>
  )
}
```

- [ ] **Step 3: Commit**

```bash
cd frontend && git add src/pages/AIModels/ModelList.tsx src/pages/AIModels/ModelForm.tsx
git commit -m "feat(phase2): add ModelList and ModelForm pages"
```

---

## Task 15: 注册前端路由 `App.tsx`

**Files:**
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: 更新 App.tsx**

将 `frontend/src/App.tsx` 替换为：

```tsx
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { useEffect } from 'react'
import { useAuthStore } from '@/stores/auth'
import AppLayout from '@/components/Layout/AppLayout'
import Login from '@/pages/Login'
import Dashboard from '@/pages/Dashboard'
import ProviderList from '@/pages/AIModels/ProviderList'
import ProviderForm from '@/pages/AIModels/ProviderForm'
import ModelList from '@/pages/AIModels/ModelList'
import ModelForm from '@/pages/AIModels/ModelForm'

function AuthRoute({ children }: { children: React.ReactNode }) {
  const isLoggedIn = useAuthStore((s) => s.isLoggedIn)
  if (!isLoggedIn) {
    return <Navigate to="/login" replace />
  }
  return <>{children}</>
}

function GuestRoute({ children }: { children: React.ReactNode }) {
  const isLoggedIn = useAuthStore((s) => s.isLoggedIn)
  if (isLoggedIn) {
    return <Navigate to="/" replace />
  }
  return <>{children}</>
}

function AppInitializer({ children }: { children: React.ReactNode }) {
  const initialize = useAuthStore((s) => s.initialize)
  const initializing = useAuthStore((s) => s.initializing)

  useEffect(() => {
    initialize()
  }, [initialize])

  if (initializing) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh' }}>
        Loading...
      </div>
    )
  }

  return <>{children}</>
}

export default function App() {
  return (
    <ConfigProvider locale={zhCN}>
      <BrowserRouter>
        <AppInitializer>
          <Routes>
            <Route
              path="/login"
              element={
                <GuestRoute>
                  <Login />
                </GuestRoute>
              }
            />
            <Route
              path="/"
              element={
                <AuthRoute>
                  <AppLayout />
                </AuthRoute>
              }
            >
              <Route index element={<Dashboard />} />
              {/* Phase 2: AI 模型管理 */}
              <Route path="providers" element={<ProviderList />} />
              <Route path="providers/new" element={<ProviderForm />} />
              <Route path="providers/:id/edit" element={<ProviderForm />} />
              <Route path="ai-models" element={<ModelList />} />
              <Route path="ai-models/new" element={<ModelForm />} />
              <Route path="ai-models/:id/edit" element={<ModelForm />} />
            </Route>
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </AppInitializer>
      </BrowserRouter>
    </ConfigProvider>
  )
}
```

- [ ] **Step 2: 前端构建验证**

```bash
cd frontend && npm run build 2>&1 | tail -20
```

预期：构建成功，无 TypeScript 错误。若有类型错误，根据报错信息修复后重跑。

- [ ] **Step 3: Commit**

```bash
cd frontend && git add src/App.tsx
git commit -m "feat(phase2): register AI model management routes in App.tsx"
```

---

## Task 16: 端到端验证

- [ ] **Step 1: 启动后端**

```bash
cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000
```

- [ ] **Step 2: 验证供应商 API（新开终端）**

```bash
# 先登录获取 token（替换 email/password 为实际值）
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@example.com","password":"your-password"}' \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['data']['access_token'])")

# 创建供应商
curl -s -X POST http://localhost:8000/api/providers \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"Test OpenAI","provider_type":"openai","api_key":"sk-test","status":true}' \
  | python3 -m json.tool

# 列出供应商
curl -s http://localhost:8000/api/providers \
  -H "Authorization: Bearer $TOKEN" \
  | python3 -m json.tool
```

预期：创建接口返回供应商数据（含 `has_api_key: true`），列表接口返回分页数据。

- [ ] **Step 3: 验证模型 API**

```bash
# 获取供应商 ID（替换为上一步返回的 id）
PROVIDER_ID=1

curl -s -X POST http://localhost:8000/api/ai-models \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"provider_id\":$PROVIDER_ID,\"name\":\"gpt-4o-mini\",\"display_name\":\"GPT-4o Mini\",\"model_type\":\"chat\",\"status\":true}" \
  | python3 -m json.tool
```

预期：返回包含模型 id 的成功响应。

- [ ] **Step 4: 启动前端验证页面**

```bash
cd frontend && npm run dev
```

打开浏览器访问 `http://localhost:5173`，登录后：
- 访问 `/providers` — 应看到供应商卡片列表
- 点击"新增供应商" — 表单页面正常打开
- 访问 `/ai-models` — 应看到模型表格

- [ ] **Step 5: 最终 Commit**

```bash
git add -A
git commit -m "feat(phase2): complete AI model management - providers, models, LangChain integration"
```

---

## 阶段检查清单

- [ ] Alembic 迁移运行成功（`ai_providers`、`ai_models` 表已创建）
- [ ] API Key 加密存储，响应中不返回明文（仅 `has_api_key` 布尔值）
- [ ] 供应商 CRUD 正常，删除时有模型依赖则返回 409
- [ ] 模型创建超出配额时返回 429
- [ ] `GET /ai-models?include_public=true` 返回租户模型 + 平台公共模型
- [ ] 供应商连通测试接口可调用
- [ ] 前端供应商列表/表单/模型列表/表单页面正常渲染
- [ ] `npm run build` 无 TypeScript 错误
