# CLAUDE.md

本文档为 AI 编码代理（Coding Agents）提供关于 AI-Studio 项目的关键信息，帮助代理在无需大量探索的情况下高效理解和修改本项目。

## 项目概述

AI-Studio 是一个企业级 AI 应用平台，采用前后端分离架构：

- **后端**：Python + FastAPI，位于 `backend/` 目录
- **前端**：React + TypeScript + Vite，位于 `frontend/` 目录
- **设计文档**：位于 `docs/` 目录

## 关键技术约定

### 后端

**框架与版本**

- FastAPI 0.136+，所有路由使用异步函数（`async def`）
- SQLAlchemy 2.0，使用 `Session` 风格（非 `AsyncSession`）
- Pydantic v2，所有请求/响应模型继承自 `BaseModel`

**多租户数据隔离（核心机制）**

所有数据访问必须通过 `BaseRepository`（`backend/app/repositories/base.py`），**禁止**直接在 Service 层裸写 `db.query(Model).all()`。

```python
# 正确：继承 BaseRepository
class PromptRepository(BaseRepository[Prompt]):
    pass

# 在 Service 中使用 get_repo() 依赖工厂
repo = get_repo(PromptRepository)(db=db, tenant_id=current_user.tenant_id)
```

- `_tenant_filter()`：过滤当前租户数据
- `_tenant_or_public_filter()`：过滤当前租户 + 平台公共数据（`tenant_id IS NULL`），用于 AI 模型、插件等支持公共资源的表

**目录结构**

```
backend/app/
├── api/          # 路由层：仅做参数校验、调用 Service、返回响应
├── services/     # 业务逻辑层：含配额检查、事务管理
├── repositories/ # 数据访问层：继承 BaseRepository，自动注入 tenant_id
├── models/       # SQLAlchemy ORM 模型
├── schemas/      # Pydantic 请求/响应模型
├── core/         # 配置、安全、依赖注入、异常
├── middleware/   # 租户隔离、审计日志、限流
└── utils/        # LLM 客户端、Embedding、加密、文档解析
```

**添加新 API 端点的步骤**

1. 在 `app/models/` 添加 ORM 模型
2. 在 `app/schemas/` 添加 Pydantic 模型
3. 在 `app/repositories/` 添加 Repository（继承 BaseRepository）
4. 在 `app/services/` 实现业务逻辑（调用 QuotaService 检查配额）
5. 在 `app/api/` 添加路由（使用 `require_permission` 守卫）
6. 在 `app/main.py` 注册路由
7. 生成 Alembic 迁移：`alembic revision --autogenerate -m "描述"`

**知识库功能**

知识库模块提供文档上传、解析、向量化存储和语义检索能力：

```python
# 知识库 CRUD（app/services/knowledge.py）
service = KnowledgeBaseService(db=db, tenant_id=current_user.tenant_id)
kb = service.create_knowledge_base(name, description, embedding_model)
docs = service.upload_document(kb_id, file_path, file_name, file_type)
chunks = service.get_chunks(doc_id)
results = service.search(kb_id, query_text, top_k=5)

# 文档解析与分块（app/utils/document.py）
from app.utils.document import DocumentParser, TextSplitter
parser = DocumentParser()
text = parser.parse(file_path)
splitter = TextSplitter(chunk_size=500, chunk_overlap=50)
chunks = splitter.split(text)

# 向量检索（集成 Qdrant）
from app.core.vector_db import get_or_create_collection, get_qdrant_client
collection_name = get_or_create_collection(kb_id=kb.id, vector_size=1536)
client = get_qdrant_client()
results = client.search(collection_name, query_vector, limit=top_k)
```

关键组件：
- `app/models/knowledge_base.py` - 知识库模型
- `app/models/knowledge_document.py` - 文档模型（含状态：pending/processing/completed/failed）
- `app/models/knowledge_chunk.py` - 文档分块模型
- `app/utils/document.py` - 文档解析器（PDF/Word/Markdown）
- `app/utils/embedding.py` - 向量化客户端（支持 OpenAI/Azure/Ollama）
- `app/core/vector_db.py` - Qdrant 客户端管理
- `app/services/knowledge_processor.py` - Celery 异步任务（文档处理流程）

**权限守卫**

```python
# 普通 RBAC 权限
from app.core.dependencies import require_permission
@router.post("/prompts", dependencies=[Depends(require_permission("prompt", "create"))])

# 超级管理员专属接口
from app.core.dependencies import require_platform_admin
@router.get("/admin/tenants", dependencies=[Depends(require_platform_admin)])
```

**统一响应格式**

所有 API 响应使用统一格式（`app/schemas/common.py`）：

```json
{ "code": 0, "message": "success", "data": {} }
```

分页响应：

```json
{ "code": 0, "message": "success", "data": { "items": [], "total": 100, "page": 1, "page_size": 20 } }
```

**异常处理**

使用 `app/core/exceptions.py` 中的自定义异常，禁止直接抛出 `HTTPException`：

```python
from app.core.exceptions import NotFoundException, ForbiddenException, QuotaExceededException

raise NotFoundException("Prompt", prompt_id)
raise ForbiddenException("prompt", "delete")
raise QuotaExceededException("users")  # 返回 HTTP 429
```

**配额检查**

创建受限资源时必须先调用 QuotaService：

- `UserService.create_user()` → `QuotaService.check_user_quota(tenant_id)`
- `AIModelService.create_model()` → `QuotaService.check_model_quota(tenant_id)`

**LLM 调用**

通过 `LLMClient`（`app/utils/llm.py`）统一调用，支持 OpenAI、Anthropic、Azure、Ollama：

```python
llm_client = LLMClient(provider, model)
result = await llm_client.ainvoke(messages)        # 普通调用
async for chunk in llm_client.astream(messages):   # 流式调用
    yield chunk
```

**SSE 流式响应**

```python
from sse_starlette.sse import EventSourceResponse

@router.post("/{agent_id}/chat")
async def chat_stream(agent_id: int, ...):
    async def event_generator():
        async for chunk in agent_service.chat_stream(...):
            yield {"data": json.dumps({"content": chunk.content})}
        yield {"data": json.dumps({"done": True})}
    return EventSourceResponse(event_generator())
```

**中间件执行顺序**（后注册先执行）

1. CORS（最外层）
2. RateLimitMiddleware（限流）
3. TenantMiddleware（租户隔离，校验租户状态）
4. AuditMiddleware（审计日志，记录写操作响应）

白名单路径（跳过租户校验）：`/api/auth/login`、`/api/auth/register`、`/api/auth/refresh`

### 前端

**目录结构**

```
frontend/src/
├── api/          # Axios 请求封装，按模块拆分
├── components/   # 通用组件（布局、守卫、分页等）
├── hooks/        # 自定义 Hooks（如 useSSE）
├── pages/        # 页面组件，按功能模块分目录
├── stores/       # Zustand 状态管理（auth、app）
├── types/        # TypeScript 类型定义
└── utils/        # 工具函数（token 存取等）
```

**状态管理**

- 认证状态：`src/stores/auth.ts`（login / logout / token / user）
- 全局 UI 状态：`src/stores/app.ts`（侧边栏折叠、主题等）

**API 请求**

所有请求通过 `src/api/client.ts` 中的 Axios 实例发起，拦截器自动注入 Bearer Token，并处理 401 自动刷新 Token 逻辑。

**SSE 流式对话**

使用 `src/hooks/useSSE.ts` Hook 订阅 SSE 事件，前端需处理 `done: true` 标志位以结束流式渲染。

**路由守卫**

- `PermissionGuard`：基于 RBAC 权限控制组件可见性
- `AdminGuard`：超级管理员路由守卫，包裹 `/admin/*` 路由组

**UI 组件库**

使用 Ant Design 6.x + `@ant-design/x`（AI 对话组件）。聊天界面优先使用 `@ant-design/x` 的 Bubble、Sender 等组件。

**知识库页面**

知识库模块包含两个主要页面：

- `src/pages/Knowledge/KnowledgeList.tsx` - 知识库列表，卡片式展示，支持创建、编辑、删除
- `src/pages/Knowledge/KnowledgeDetail.tsx` - 知识库详情，包含文档管理（上传、列表、状态）和语义检索功能

路由配置：
```typescript
<Route path="knowledge" element={<KnowledgeList />} />
<Route path="knowledge/:kbId" element={<KnowledgeDetail />} />
```

文档上传流程：
1. 用户拖拽或选择文件上传
2. 后端接收文件并创建文档记录（状态为 `pending`）
3. Celery 异步任务处理文档（解析 → 分块 → 向量化 → 存入 Qdrant）
4. 前端通过状态指示器显示处理进度（pending → processing → completed/failed）

## 数据库设计要点

- 所有租户相关表均包含 `tenant_id` 字段，且必须通过 `BaseRepository` 查询
- 软删除统一使用 `deleted_at` 字段（`NULL` 表示未删除）
- 平台公共资源（公共 AI 模型、公共插件）的 `tenant_id` 为 `NULL`
- 向量数据存储在独立的 Qdrant 实例中（`app/core/vector_db.py`），每个知识库对应一个 Collection（命名规则：`kb_{kb_id}`）
- 审计日志和 Token 用量记录永久保留，其他业务数据软删除后 90 天可物理清除

## 运行与测试

### 后端

```bash
# 启动
cd backend
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000

# 数据库迁移
alembic upgrade head
alembic revision --autogenerate -m "add xxx table"

# 健康检查
curl http://localhost:8000/health
```

### 前端

```bash
cd frontend
npm run dev      # 开发模式
npm run build    # 构建生产包
npm run lint     # ESLint 检查
```

## 常见问题

**Q: 新增模型后 API 返回的数据包含了其他租户的数据？**

A: 检查对应 Repository 是否继承了 `BaseRepository`，以及查询时是否使用了 `_tenant_filter()` 或 `_tenant_or_public_filter()`。

**Q: 如何添加一个新的 LLM 供应商？**

A: 在 `backend/app/utils/llm.py` 的 `LLMClient._build_chain()` 方法中增加新的 `elif` 分支，实例化对应的 LangChain `BaseChatModel` 子类。

**Q: 工作流节点如何新增类型？**

A: 在 `backend/app/services/workflow_engine.py` 的 `_execute_node()` 方法中添加新分支，实现 `_execute_xxx_node()` 执行器方法。

**Q: 前端如何接入一个新的 SSE 接口？**

A: 使用 `src/hooks/useSSE.ts` Hook，传入目标 URL，监听 `message` 事件并解析 `data` 字段，判断 `done: true` 时停止。

**Q: 如何添加知识库功能？**

A: 知识库功能已在阶段4实现完整，包括：
- 知识库 CRUD：通过 `KnowledgeBaseService` 实现
- 文档上传：调用 `/knowledge/knowledge-bases/{kb_id}/documents/upload` 接口
- 文档处理：Celery 异步任务自动处理（解析 → 分块 → 向量化）
- 向量检索：使用 Qdrant 进行语义搜索，返回相似度评分

**Q: 知识库文档处理失败怎么办？**

A: 检查以下几点：
1. Celery worker 是否正常运行（`celery -A app.core.celery_app worker --loglevel=info`）
2. Embedding 客户端配置是否正确（检查 `config.embedding_provider` 和 `config.embedding_model`）
3. Qdrant 连接是否正常（检查 `config.qdrant_url` 和 `config.qdrant_api_key`）
4. 文档格式是否支持（目前支持 PDF、Word、Markdown、TXT）
5. 查看 `knowledge_documents.error_message` 字段获取错误详情

**Q: 如何更改知识库的向量模型？**

A: 在创建知识库时指定 `embedding_model` 参数（如 `text-embedding-3-small` 或 `BAAI/bge-m3`），注意：
- 不同向量模型的向量维度不同（如 OpenAI text-embedding-3-small 为 1536，BAAI/bge-m3 为 1024）
- Qdrant Collection 的 `vector_size` 必须与向量模型匹配
- 已创建的知识库无法更改向量模型（需删除重建）

## 参考文档

- [系统架构设计](docs/architecture.md)
- [API 路由设计](docs/api-design.md)
- [数据库设计](docs/database-design.md)
- [核心机制实现](docs/core-mechanisms.md)
- [前端设计](docs/frontend-design.md)
- [分阶段实施计划](docs/implementation-plan.md)
