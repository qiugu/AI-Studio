# Phase 2 设计文档：AI 模型管理

**日期**: 2026-06-02
**阶段**: Phase 2 — AI Model Management
**依赖**: Phase 1（认证/RBAC/中间件/BaseRepository）已完成

---

## 目标

实现 AI 供应商（AIProvider）和 AI 模型（AIModel）的完整 CRUD 管理，集成 LangChain 实现多供应商 LLM 调用，提供供应商连通性测试和模型调用测试能力。

---

## 数据模型

### ai_providers（AI供应商表）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | BigInteger PK | 主键 |
| tenant_id | BigInteger FK | 所属租户 |
| name | String(255) | 供应商显示名称 |
| provider_type | String(50) | 类型：openai / anthropic / azure / zhipu / baichuan / ollama / custom |
| api_base_url | String(500) | API 基础 URL（可选，Ollama 等本地部署时必填）|
| api_key_encrypted | Text | Fernet 加密存储的 API Key |
| config | JSON | 额外配置（请求头、超时等） |
| status | Boolean | 启用状态 |
| created_at | DateTime | 创建时间 |
| updated_at | DateTime | 更新时间 |

### ai_models（AI模型配置表）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | BigInteger PK | 主键 |
| tenant_id | BigInteger FK | 所属租户（NULL 表示平台预置模型） |
| provider_id | BigInteger FK | 所属供应商 |
| name | String(255) | 模型标识（gpt-4o、claude-3-sonnet 等）|
| display_name | String(255) | 显示名称 |
| model_type | String(50) | 类型：chat / embedding / image / audio / rerank |
| config | JSON | 模型配置（temperature 范围、上下文长度等）|
| unit_price_input | Decimal(10,6) | 输入单价（每千 token，美元）|
| unit_price_output | Decimal(10,6) | 输出单价 |
| max_context_tokens | Integer | 最大上下文 token 数 |
| max_output_tokens | Integer | 最大输出 token 数 |
| status | Boolean | 启用状态 |
| created_at | DateTime | 创建时间 |
| updated_at | DateTime | 更新时间 |

**可见性规则**：`tenant_id IS NULL` 表示平台预置模型，所有租户只读可用；写操作仅限 `is_platform_admin=true`。

---

## 后端组件

### `app/utils/encryption.py`
- 使用 `cryptography.fernet.Fernet` 对称加密
- `encrypt(plaintext: str) -> str` — 加密并返回 base64 字符串
- `decrypt(ciphertext: str) -> str` — 解密还原明文
- Fernet key 从环境变量 `ENCRYPTION_KEY` 读取

### `app/utils/llm.py`
- `build_chat_model(provider, model_name, **overrides)` — 根据供应商类型动态构建 LangChain `BaseChatModel`
- 支持：openai → `ChatOpenAI`，anthropic → `ChatAnthropic`，azure → `AzureChatOpenAI`，ollama → `ChatOllama`，其余走 `ChatOpenAI` 兼容模式
- 连通性测试：先尝试调用供应商 `/models` 列表接口；失败则回退到发送一条简单 LLM 消息

### `app/models/ai_provider.py` + `app/models/ai_model.py`
- 遵循现有模型规范（`mapped_column`、`Mapped` 类型注解）
- `ai_models` 无 `deleted_at`（硬删除）；`ai_providers` 同理

### `app/services/ai_provider.py`
- `AIProviderService(db, tenant_id)` — CRUD
  - `create(data)` — 加密 API Key 后存储
  - `list(page, page_size, status)` → PaginatedResponse
  - `get(id)` — 找不到抛 NotFoundException
  - `update(id, data)` — 仅更新非 None 字段
  - `delete(id)` — 硬删除（同时检查是否有模型依赖）
  - `test_connectivity(id, model_name)` — 连通性测试，返回 `{success, latency_ms, error}`

### `app/services/ai_model.py`
- `AIModelService(db, tenant_id)` — CRUD
  - `create(data)` — 先调 `QuotaService.check_model_quota()` 再创建
  - `list(page, page_size, model_type, provider_id, include_public)` — `include_public=True` 时用 `_tenant_or_public_filter()`
  - `get(id)` — 找不到抛 NotFoundException
  - `update(id, data)`
  - `delete(id)` — 硬删除
  - `test_model(id, messages)` — 调用 LLM 返回输出

### `app/services/quota.py`（修复）
- `check_model_quota()` 中替换占位符为真实 `AIModel` 查询

### `app/api/ai_provider.py`
```
GET    /providers           列表（分页）
POST   /providers           创建
GET    /providers/{id}      详情
PUT    /providers/{id}      更新
DELETE /providers/{id}      删除
POST   /providers/{id}/test 连通性测试
```

### `app/api/ai_model.py`
```
GET    /ai-models                    列表（?include_public=true）
POST   /ai-models                    创建
GET    /ai-models/{id}               详情
PUT    /ai-models/{id}               更新
DELETE /ai-models/{id}               删除
POST   /ai-models/{id}/test          模型调用测试
```

所有接口均需认证（`CurrentUser` 依赖），敏感操作需 `model:write` 权限。

---

## 前端组件

### `src/types/ai-model.ts`
定义 `AIProvider`、`AIModel`、相关 Request/Response 接口。

### `src/api/ai-model.ts`
封装所有供应商和模型的 axios 请求，包括连通测试接口。

### 页面组件

| 路由 | 组件 | 说明 |
|------|------|------|
| `/providers` | `ProviderList.tsx` | 供应商卡片列表，状态指示灯，操作按钮 |
| `/providers/new` + `/providers/:id/edit` | `ProviderForm.tsx` | 创建/编辑表单，包含连接测试按钮 |
| `/ai-models` | `ModelList.tsx` | 模型表格，支持类型/供应商筛选 |
| `/ai-models/new` + `/ai-models/:id/edit` | `ModelForm.tsx` | 模型创建/编辑表单 |

### 连接测试 Modal
- 独立组件 `ConnectionTestModal.tsx`
- 显示测试状态（loading / 成功 / 失败）和延迟时间

---

## 安全考量

- API Key 在后端 Fernet 加密存储，接口响应中 **不返回** 解密后的 Key（仅返回是否已配置）
- `tenant_id IS NULL` 的公共模型只读，写操作由 `require_platform_admin` 守卫
- 连通测试接口限制调用频率（复用 RateLimitMiddleware）

---

## 迁移

执行 Alembic 自动生成迁移脚本，新增 `ai_providers` 和 `ai_models` 表。
