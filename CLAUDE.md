# CLAUDE.md

本文档为 AI 编码代理（Coding Agents）提供关于 AI-Studio 项目的关键信息，帮助代理在无需大量探索的情况下高效理解和修改本项目。

## 项目概述

AI-Studio 是一个企业级 AI 应用平台，采用前后端分离架构：

> 当前代码库已完成一轮主键与外键规范统一：核心业务 ID 统一为字符串 UUID v4，数据库层以 `varchar(36)` 存储，后端模型、Alembic 迁移和前端接口/页面调用已同步适配。

- **后端**：Python + FastAPI，位于 `backend/` 目录
- **前端**：React + TypeScript + Vite，位于 `frontend/` 目录
- **设计文档**：位于 `docs/` 目录

## 关键技术约定

### 后端

**框架与版本**

- FastAPI 0.136+，所有路由使用异步函数（`async def`）
- 数据库主键/外键/租户字段统一使用字符串 UUID v4，模型定义为 `String(36)`，默认值通过 `str(uuid.uuid4())` 生成
- SQLAlchemy 2.0，使用 `Session` 风格（非 `AsyncSession`）
- Pydantic v2，所有请求/响应模型继承自 `BaseModel`

**多租户数据隔离（核心机制）**

> 修改模型或新增字段时，优先确认是否需要同步更新：SQLAlchemy 模型、Alembic 迁移、前端类型定义与 API 调用。

当前实现：**租户隔离由执行期全局过滤器强制保证**，而非依赖每个 Service 当次是否记得加过滤。`core/tenant_scope.py` 通过 `Session.do_orm_execute` + `with_loader_criteria`，在 ORM 的 SELECT 语句执行前自动注入当前租户的 `tenant_id` 条件（覆盖 `query()` 与 `select()`），**不可被绕过**；平台公共行（如 `tenant_id IS NULL` 的 AI 模型、`tenant_id IS NULL AND is_public` 的插件）的可见性由模型声明的 `__tenant_scope_clause__` 控制（见 `core/tenant_scope.py`）。

> 设计取舍：SQLAlchemy `Session` 本身已是 Unit-of-Work + Repository 抽象，对大量一次性查询再包一层泛型 `BaseRepository` 属贫血包装反模式。`BaseRepository`（`backend/app/repositories/base.py`）仅被 conversation / knowledge / workflow / agent 四个模块复用；其余 Service 直接操作注入的 `self.db`（`Session`）。租户隔离的**唯一事实来源是全局过滤器**，而非"走没走 BaseRepository"。

Service 层查询约定（分层，非一刀切）：
- 简单单模型 CRUD / 一次性过滤：直接使用注入的 `Session`（租户条件由全局过滤器兜底）；
- 跨模型、复杂或复用的查询：抽到 `Repository` / `Query Object`；
- 含平台公共行（`tenant_id IS NULL`）的可见性：统一调用 `public_or_tenant_filter(model, tenant_id, include_public=...)`，其公共行规则与模型 `__tenant_scope_clause__` 一致，**禁止手写 `tenant_id` 过滤条件**（由全局过滤器统一处理，避免语义分歧与越权）。

```python
# 实际用法：公共行可见性统一走共享 helper（单一事实来源）
q = self.db.query(AIModel).filter(
    public_or_tenant_filter(AIModel, self.tenant_id, include_public=True)
)
```

- 范围说明：上一条"所有查询必须经 BaseRepository"的原约定未被贯彻（Service 层存在大量裸 `self.db.query/execute`）；本说明将其正式调整为上述分层约定，详见 `docs/plan-convention-alignment.md`（条目 S3）。
- 注意范围：`with_loader_criteria` 仅覆盖 ORM SELECT；Core 层 `text()` 原生 SQL、以及 ORM `UPDATE` / `DELETE` 不在此钩子范围内，仍需业务层自行保证租户条件。

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
3. 在 `app/repositories/` 添加 Repository（继承 `BaseRepository`；当前仅部分模块使用，其他模块在 Service 内手写查询并手工注入 `tenant_id`）
4. 在 `app/services/` 实现业务逻辑（调用 QuotaService 检查配额）
5. 在 `app/api/` 添加路由（按模块使用 `require_permission` 守卫；`ai_provider` / `ai_model` / `prompt` / `plugin` 当前仅做登录校验 `CurrentUser`，未做细粒度权限，见 `docs/review` S2）
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

当前覆盖情况（实际）：
- 已使用 `require_permission` 的路由：`knowledge` / `agent` / `workflow` / `audit` / `admin` / `role` / `user` / `system`。
- **仅做登录校验（`CurrentUser`）、未做细粒度 RBAC 的路由**：`ai_provider` / `ai_model` / `prompt` / `plugin`。
- ⚠️ **已知偏差**：上述四个模块的写操作当前任何已登录用户均可调用，属权限缺口（详见 `docs/review/01-backend.md` S2）。

**统一响应格式**

约定响应结构（`app/schemas/common.py` 的 `ResponseBase`：`code` / `message` / `data`；`PaginatedResponse` / `PaginatedData` 用于分页）：

```json
{ "code": 0, "message": "success", "data": {} }
```

```json
{ "code": 0, "message": "success", "data": { "items": [], "total": 100, "page": 1, "page_size": 20 } }
```

当前实现要点：
- 成功响应由**各路由自行构造**该结构（多数为手写 `{"code": 0, "message": "success", "data": ...}` 字典，少数使用 `ResponseBase.ok()`）。
- 错误响应经全局异常处理器统一为 `{"code": <HTTP状态码>, "message": <错误信息>, "data": null}`（见下节）。
- 约定"禁止直接抛 `HTTPException`"已落地：`api/` 下已无裸 `raise HTTPException`（`knowledge.py` 等全部改用 `AppException` 子类；全局处理器亦保证任何遗留 `HTTPException` 都返回统一信封）。详见 `docs/plan-convention-alignment.md`（条目 C1）。

**异常处理**

使用 `app/core/exceptions.py` 中的 `AppException`（继承自 `HTTPException`）及其子类表达领域错误，由 `main.py` 的全局异常处理器统一转换为 `{code, message, data}`：

```python
from app.core.exceptions import NotFoundException, ForbiddenException, QuotaExceededException

raise NotFoundException("Prompt", prompt_id)   # → 404 {code:404, message, data:null}
raise ForbiddenException("prompt", "delete")    # → 403
raise QuotaExceededException("users")           # → 429
```

- 全局处理器：`AppException` → `{code: <HTTP状态码>, message: <detail>, data: null}`；Pydantic `ValidationError` → `{code:422, message:"Validation error", data: errors}`；未捕获 `Exception` → `{code:500, message:"Internal server error", data:null}`。
- `AppException` 本身是 `HTTPException` 子类，因此全局处理器对裸 `HTTPException` 也返回统一信封；但约定仍要求**新增代码优先使用 `AppException` 子类**（`api/` 下已无裸 `raise HTTPException`，详见 `docs/plan-convention-alignment.md` C1）。

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

后端使用 `StreamingResponse` 返回 SSE 字节流。实际端点：`POST /agent/agents/{agent_id}/chat/stream`（`agent_id` 为 UUID 字符串），位于 `backend/app/api/agent.py`：

```python
from fastapi.responses import StreamingResponse
from app.schemas.stream import StreamChunk   # SSE 帧模型
from app.utils.llm import encode              # 序列化为 SSE 文本

@router.post(
    "/agents/{agent_id}/chat/stream",
    dependencies=[Depends(require_permission("agent", "chat"))],
)
async def chat_stream(agent_id: str, data: ChatRequest, ...):
    async def event_generator():
        async for chunk in agent_service.chat_stream(...):
            if chunk["type"] == "message":
                yield encode(StreamChunk(event="message",
                            data=json.dumps({"content": chunk["content"]}, ensure_ascii=False)))
            elif chunk["type"] == "done":
                yield encode(StreamChunk(event="done",
                            data=json.dumps({"conversation_id": conversation_id}, ensure_ascii=False)))
            elif chunk["type"] == "error":
                yield encode(StreamChunk(event="error",
                            data=json.dumps({"error": ..., "error_code": ...}, ensure_ascii=False)))
    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

**关键约定**：
- SSE 帧格式：`event: message\ndata: {...}\n\n`（由 `encode(StreamChunk(...))` 生成）。
- JSON 序列化必须使用 `ensure_ascii=False` 以保留 Unicode 字符。
- Media Type 必须设置为 `text/event-stream`。
- 事件类型：`message`（含 `content`）、`done`（含 `conversation_id`）、`error`（含 `error` 与 `error_code`）。

**中间件执行顺序**（后注册先执行）

1. CORS（最外层）
2. RateLimitMiddleware（限流）
3. TenantMiddleware（租户隔离，校验租户状态）
4. AuditMiddleware（审计日志，记录写操作响应）

白名单路径（跳过租户校验）：`/api/auth/login`、`/api/auth/register`、`/api/auth/refresh`

### 出站调用（SSRF 防护）

凡**目标地址由租户/用户配置**的出站 HTTP 调用，请求前必须经
`app/utils/net_guard.assert_outbound_url_allowed(url)` 校验，且**不跟随重定向**：

- 适用对象：插件调用（`app/utils/plugin_executor.py`）、Agent 的 `api` 工具
  （`app/services/agent.py`），以及任何新增的类似能力。
- 校验时机：用**路径参数替换之后**的最终 URL；早于替换会让 `//host` 形态的路径改写主机名而绕过校验。
- 拒绝范围：非 `http(s)` 协议、`localhost` 子域、私有/环回/链路本地（含云元数据
  `169.254.169.254`）/保留/组播/未指定网段、`100.64.0.0/10`（CGNAT，`ipaddress` 标志位未覆盖）。
- 部署确需访问内网时，显式关闭 `PLUGIN_BLOCK_PRIVATE_NETWORK`（默认 `true`），
  并同时以网络层策略限制出站范围。

### Agent 工具授权（设计期为主控，运行时为兜底）

**授权清单即能力边界**：Agent 能用哪些插件由 `agent_tools` 的条目集合决定；未绑定的插件
不进入工具池，也不占用模型上下文。控制点必须在**设计期**，运行时门禁只作兜底。

**设计期（主控）**

- 候选面由服务端裁剪，前端只展示、不重复判断可用性：
  `PluginService.list_bindable_for_agent` / `GET /api/agent/agents/tool-catalog`，
  条件为 本租户或公共 ∧ `status=active` ∧ `source_type=http` ∧ 端点 ≥ 1。
- 授权粒度到**端点**（`plugin_id` + `endpoint_id`），不是插件；破坏性端点默认隐藏且需二次确认，
  确认后写入 `allow_destructive: true`。
- 写入前必须校验（`AgentService._validate_tool_bindings`）：**任一条非法即整体拒绝**
  （`ValidationException`），不得逐条静默跳过；更新时校验须先于删除旧工具。
- 候选裁剪与写入校验**共用** `plugin_policy.check_plugin_bindable`，不得各写一套。
- 生成的工具 `name` 会作为 function name 传给模型，须匹配 `^[a-zA-Z0-9_-]{1,64}$`
  （中文插件名退回 `plugin-{id 前 8 位}`），中文说明放 `description`。
- 路由顺序陷阱：`/agents/tool-catalog` 必须声明在 `/agents/{agent_id}` **之前**，
  否则会被当作 `agent_id` 吞掉。

**运行时（兜底）**——防止授权清单在保存后被外部改坏；不通过则**跳过并记录告警**（fail-closed）：

1. 插件状态为 `active`（`disabled` / `pending_review` 不可暴露）；
2. 工具配置**显式**指定 `endpoint_id` 或 `endpoint`——禁止回退到「首个端点」；
3. `DELETE` / `PUT` / `PATCH` 默认不暴露，需显式 `allow_destructive: true`（布尔，字符串不算）。

端点解析统一走 `plugin_policy.resolve_bound_endpoint`，设计期与运行时不得各写一套。

新增任何「把外部能力暴露给模型」的工具类型时，须比照本条补齐等效的候选裁剪与写入校验。

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

请求客户端存在两份 Axios 实例：
- `src/api/client.ts`：注册响应拦截器，将响应归一为 `response.data`（前端多数模块经此实例调用）。
- `src/utils/request.ts`：注册请求/响应拦截器，负责注入 Bearer Token 与 401 自动刷新。

⚠️ **已知偏差**：两套拦截器并存，刷新 Token 的队列逻辑在刷新失败分支未对挂起请求 `resolve`/`reject`，会导致排队请求永久挂起（详见 `docs/review/02-frontend.md` E9）。新增请求建议统一走 `src/api/client.ts`。

**SSE 流式对话**

实际实现：使用 `src/utils/streamRequest.ts` 中的 `createStreamRequest` / `createWorkflowStreamRequest`（基于 `fetch` + `ReadableStream`，以 `POST` 发送请求体并逐块读取 SSE），**而非** `src/hooks/useSSE.ts`（`useSSE.ts` 当前未被任何组件引用，属死代码）。

调用位置：`src/pages/Agents/AgentChat.tsx`、`src/pages/Workflows/WorkflowExecution.tsx`。

**SSE 解析关键点**：
- 基于 fetch + ReadableStream 读取，正确解析 SSE 消息边界（以 `\n\n` 分隔）
- 处理三种事件类型：
  - `message` 事件：包含 `content` 字段（AI 输出的文本块）
  - `done` 事件：包含 `conversation_id` 字段（对话 ID）
  - `error` 事件：包含 `error` 和 `error_code` 字段
- 支持用户中断（`AbortController`，组件卸载时 `abort()`）
- Buffer 处理：保留跨数据块的不完整消息

**路由守卫**

- `PermissionGuard`：基于 RBAC 权限控制组件可见性
- `AdminGuard`：超级管理员路由守卫，包裹 `/admin/*` 路由组

**UI 组件库**

使用 Ant Design 6.x + `@ant-design/x`（AI 对话组件）。聊天界面优先使用 `@ant-design/x` 的 Bubble、Sender 等组件。

**关键前端组件**：
- `MarkdownRenderer.tsx` - Markdown 渲染组件：
  - 使用 `react-markdown` + `remark-gfm` + `rehype-highlight` + `rehype-raw`
  - 支持 GitHub Flavored Markdown (GFM)
  - 代码高亮（highlight.js，github-dark 主题）
  - 表格滚动包装器
  - 链接新窗口打开
- `ConversationList.tsx` - 对话历史列表：
  - 时间分组导航（今天、昨天、本周、更早）
  - 相对时间显示（使用 dayjs）
  - 消息预览（截断 50 字符）+ 消息计数徽标
  - 悬停操作菜单（重命名、删除）
  - 性能优化（React.memo、useMemo）
- `MessageBubble.tsx` - 消息气泡：
  - 用户消息：蓝色背景（`bg-blue-500`）、右对齐、UserOutlined 图标、胶囊形状
  - AI 消息：灰色背景（`bg-gray-100`）、左对齐、RobotOutlined 图标、圆角矩形
  - 12px 气泡间距
- `ChatContainer.tsx` - 对话容器：
  - 基于 `@ant-design/x` 的 `Bubble.List`，支持虚拟滚动（超过 50 条消息自动启用）
  - 流式渲染状态管理

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

**工作流引擎**

工作流模块提供基于 DAG 的可视化工作流编排和执行能力：

```python
# 工作流 CRUD（app/services/workflow.py）
service = WorkflowService(db=db, tenant_id=current_user.tenant_id)
workflow = service.create_workflow(name, description, nodes, edges)
workflow = service.publish_workflow(workflow_id)
service.validate_workflow_dag(workflow_id)

# 工作流执行（app/services/workflow_engine.py）
engine = WorkflowEngine(db=db, tenant_id=current_tenant.id)
execution = await engine.execute(workflow_id=workflow.id, input_data={"key": "value"}, user_id=current_user.id)

# 流式执行（SSE）
async for event in engine.execute_stream(workflow_id=workflow.id, input_data={}, user_id=current_user.id):
    yield event
```

关键组件：
- `app/models/workflow.py` - 工作流模型
- `app/models/workflow_node.py` - 工作流节点模型（支持 start、end、llm、condition、knowledge、code、tool、loop、input、output 类型）
- `app/models/workflow_edge.py` - 工作流边模型
- `app/models/workflow_execution.py` - 工作流执行记录
- `app/models/node_execution.py` - 节点执行记录
- `app/services/workflow.py` - 工作流 CRUD 服务
- `app/services/workflow_engine.py` - 工作流执行引擎（DAG 拓扑排序、节点执行器分发、上下文传递）
- `app/api/workflow.py` - 工作流 API 路由（含 SSE 流式执行）
- `src/pages/Workflows/WorkflowList.tsx` - 工作流列表页面
- `src/pages/Workflows/WorkflowEditor.tsx` - 工作流编辑器（React Flow 画布）
- `src/pages/Workflows/WorkflowExecution.tsx` - 工作流执行面板

工作流节点类型：
- `start` - 开始节点
- `end` - 结束节点
- `llm` - LLM 节点（调用大语言模型）
- `condition` - 条件节点（条件判断路由）
- `knowledge` - 知识库节点（向量检索）
- `code` - 代码节点（沙盒执行受限 Python）
- `tool` - 工具节点（调用 Agent 工具）
- `loop` - 循环节点（循环/迭代）
- `input` - 输入节点
- `output` - 输出节点

## 数据库设计要点

- 租户相关表通常包含 `tenant_id` 字段，查询时需在 Service 层注入 `tenant_id` 条件（见上文「多租户数据隔离」）。⚠️ 已知偏差：`prompt_version` 表缺少 `tenant_id`（纵深防御缺口，详见 `docs/review/01-backend.md` S4）。
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

A: 检查该查询是否注入了 `tenant_id` 条件（Service 内的 `_base_query()` / `_base_filter(include_public=...)` 等辅助方法，或 `BaseRepository` 的 `_tenant_filter()` / `_tenant_or_public_filter()`）。当前并非所有查询都经过统一封装，需逐查询确认。

**Q: 如何添加一个新的 LLM 供应商？**

A: 在 `backend/app/utils/llm.py` 的 `LLMClient._build_chain()` 方法中增加新的 `elif` 分支，实例化对应的 LangChain `BaseChatModel` 子类。

**Q: 工作流节点如何新增类型？**

A: 在 `backend/app/services/workflow_engine.py` 的 `_execute_node()` 方法中添加新分支，实现 `_execute_xxx_node()` 执行器方法。

**Q: 如何调试工作流执行问题？**

A: 检查以下几点：
1. 查看工作流执行记录（`workflow_executions` 表）和节点执行记录（`node_executions` 表）
2. 检查节点配置是否正确（如 LLM 节点的 model_id 和 prompt_template）
3. 验证 DAG 结构是否有效（调用 `validate_workflow_dag()` 方法）
4. 查看执行日志中的错误信息和堆栈跟踪

**Q: 工作流执行支持哪些输入输出格式？**

A: 工作流输入输出使用 JSON 格式：
- 输入数据：`{"input_data": {"key": "value"}}`
- 输出数据：`{"output_data": {"result": "value"}, "status": "completed"}`
- 流式执行通过 SSE 返回节点级别的执行日志

**Q: 前端如何接入一个新的 SSE 接口？**

A: 使用 `src/utils/streamRequest.ts` 的 `createStreamRequest(url, options)`，其基于 fetch + ReadableStream 读取 SSE；在回调中监听 `message` 事件解析 `data.content`，收到 `done` 事件时结束渲染，收到 `error` 事件时提示错误（`useSSE.ts` 当前未被使用）。

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
