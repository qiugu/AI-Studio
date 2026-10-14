# AI-Studio API路由设计

所有API前缀: `/api`

> **前缀实现方式**：应用内路由**不带** `/api`（例如 `/auth`、`/agent`），`/api` 由网关层添加——
> 开发环境由 Vite 代理 `rewrite` 剥离（`frontend/vite.config.ts`），生产环境由 Nginx `location /api/` 剥离
> （`frontend/nginx.conf`）。本文档表格中的路径均为**客户端可见路径**（含 `/api` 前缀）。
> 历史上后端曾使用 `openapi_prefix="/api"` 参数，该参数在 FastAPI 中已废弃，现已移除。

> **文档一致性状态**：§4、§5、§6、§9、§11、§13、§14 已逐条对照实现核对并修订
> （未实现/已移除的条目已显式标注）。其余章节仍为设计稿，未逐条验证。

通用响应格式（成功 / 失败信封的**单一权威定义**，C2）:

```jsonc
// 成功
{
  "code": 0,                 // 固定为 0
  "message": "success",
  "data": {}                 // 业务数据；分页接口为 { items, total, page, page_size }
}

// 失败（由全局异常处理器统一产出，结构稳定）
{
  "code": 400,               // 取 HTTP 状态码（400/401/403/404/409/422/429/502…）
  "error_code": "NOT_FOUND", // 业务错误码（字符串），仅 AppException 派生类携带；
                             // 裸 HTTPException（如参数校验）无此字段
  "message": "Resource not found (id=1)",
  "data": null
}
```

> 约定：前端**仅按 `code === 0` 判定成功**，不依赖具体错误码取值；`error_code`
> 仅供需要按错误类型差异化处理的场景（如 `QUOTA_EXCEEDED` 跳转充值页）。
> 限流触发时返回 `code: 429` 并带 `Retry-After` / `X-RateLimit-*` 响应头。

分页响应格式:
```json
{
  "code": 0,
  "message": "success",
  "data": {
    "items": [],
    "total": 100,
    "page": 1,
    "page_size": 20
  }
}
```

---

## 1. 认证 `/api/auth`

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /auth/login | 登录，返回JWT |
| POST | /auth/register | 已关闭自助注册（返回 403）；租户由平台管理员开通 |
| POST | /auth/refresh | 刷新Token |
| POST | /auth/change-password | 当前登录用户修改自己的密码；成功后旧会话失效 |
| POST | /auth/password-reset | 使用一次性令牌完成密码重置；成功后旧认证会话失效 |
| POST | /auth/logout | 登出 |
| GET | /auth/me | 获取当前用户信息 |

租户管理员账号由平台管理员在创建租户时指定邮箱和初始密码。成员账号由租户管理员在用户管理中创建，默认绑定当前租户的 `tenant_member` 角色。

---

## 2. 用户管理 `/api/users`

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| GET | /users | 用户列表(分页) | user:read |
| GET | /users/me | 当前用户详情 | - |
| PUT | /users/me | 更新当前用户信息 | - |
| PUT | /users/me/avatar | 上传头像 | - |
| GET | /users/{id} | 用户详情 | user:read |
| PUT | /users/{id} | 更新用户 | user:update |
| POST | /users/{id}/password-reset | 发起密码重置邮件（不接收管理员指定的新密码） | user:update + 当前密码再认证 |
| DELETE | /users/{id} | 删除用户(软删除) | user:delete |
| PUT | /users/{id}/status | 启用/禁用用户 | user:update |
| PUT | /users/{id}/roles | 设置用户角色 | user:update |

用户管理安全边界：租户管理员不提供成员密码修改入口；用户密码只能由本人从右上角账号菜单修改。
修改密码要求当前密码再认证，成功后旧访问令牌和刷新令牌失效。忘记密码时仍可使用一次性重置链接流程，
但该流程不属于用户管理编辑操作。昵称不是身份标识，审计应始终使用不可变用户 ID 和邮箱快照追踪用户。

---

## 3. 角色与权限 `/api/roles`

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| GET | /roles | 角色列表 | role:read |
| POST | /roles | 创建角色 | role:create |
| GET | /roles/{id} | 角色详情 | role:read |
| PUT | /roles/{id} | 更新角色 | role:update |
| DELETE | /roles/{id} | 删除角色 | role:delete |
| PUT | /roles/{id}/permissions | 设置角色权限 | role:update |
| GET | /roles/permissions | 全部权限列表 | role:read |

---

## 4. 租户管理（无独立 `/api/tenants` 路由）

> **实现说明**：后端**未实现** `/api/tenants` 独立路由。租户能力实际分布在两处：
> - 当前租户信息的读取/更新：`GET|PUT /api/system/tenant`（`backend/app/api/system.py`）
> - 租户的创建/启停/套餐/统计：`/api/admin/tenants/*`（见 §14，仅平台超级管理员）
>
> 下表为**原始设计稿**，保留以供后续演进参考，当前均未实现：

| 方法 | 路径 | 说明 | 权限 | 状态 |
|------|------|------|------|------|
| GET | /tenants/current | 当前租户信息 | - | ❌ 未实现（实际：`GET /api/system/tenant`） |
| PUT | /tenants/current | 更新租户信息 | tenant:update | ❌ 未实现（实际：`PUT /api/system/tenant`） |
| GET | /tenants/current/members | 租户成员列表 | tenant:read | ❌ 未实现 |
| PUT | /tenants/current/members/{user_id}/role | 修改成员角色 | tenant:update | ❌ 未实现 |

---

## 5. API密钥 `/api/api-keys`（未实现，已移除死代码）

> **状态**：该能力**未实现**。仓库中原先只存在未被任何 service / route 引用的死代码
> （`models/api_key.py`、`core/security.generate_api_key`），已按评审结论 **A2** 删除
> （见 `docs/review/01-backend.md`），并附带 Alembic 迁移 `b2c3d4e5f6a7` 清理孤立的 `api_keys` 表。
> 下表为**原始设计稿**，如需该能力应另行立项实现：

| 方法 | 路径 | 说明 | 权限 | 状态 |
|------|------|------|------|------|
| GET | /api-keys | 密钥列表 | api_key:read | ❌ 未实现 |
| POST | /api-keys | 创建密钥(返回明文key) | api_key:create | ❌ 未实现 |
| DELETE | /api-keys/{id} | 删除密钥 | api_key:delete | ❌ 未实现 |
| PUT | /api-keys/{id}/status | 启用/禁用密钥 | api_key:update | ❌ 未实现 |

---

## 6. AI供应商 `/api/providers`

> 实际注册前缀为 `/providers`（`backend/app/main.py`），而非 `/ai-providers`。
> 权限守卫为 `require_tenant_admin`（租户级配置资源，仅租户管理员可写）。

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| GET | /providers | 供应商列表 | require_tenant_admin |
| POST | /providers | 创建供应商 | require_tenant_admin |
| GET | /providers/{id} | 供应商详情 | require_tenant_admin |
| PUT | /providers/{id} | 更新供应商 | require_tenant_admin |
| DELETE | /providers/{id} | 删除供应商 | require_tenant_admin |
| POST | /providers/{id}/test | 测试连通性 | require_tenant_admin |

---

## 7. AI模型 `/api/ai-models`

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| GET | /ai-models | 模型列表(支持按type/provider筛选) | model:read |
| POST | /ai-models | 创建模型 | model:create |
| GET | /ai-models/{id} | 模型详情 | model:read |
| PUT | /ai-models/{id} | 更新模型 | model:update |
| DELETE | /ai-models/{id} | 删除模型 | model:delete |
| POST | /ai-models/{id}/test | 调用测试 | model:execute |

**查询参数**: `?type=chat&provider_id=1&include_public=true&page=1&page_size=20`

- `include_public=true`（默认 true）: 同时返回租户私有模型 + 平台公共模型（`tenant_id IS NULL`）

---

## 8. Prompt管理 `/api/prompts`

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| GET | /prompts | Prompt列表(分页+筛选) | prompt:read |
| POST | /prompts | 创建Prompt | prompt:create |
| GET | /prompts/{id} | Prompt详情(含当前版本内容) | prompt:read |
| PUT | /prompts/{id} | 更新Prompt元信息 | prompt:update |
| DELETE | /prompts/{id} | 删除Prompt | prompt:delete |
| GET | /prompts/{id}/versions | 版本列表 | prompt:read |
| GET | /prompts/{id}/versions/{version} | 特定版本详情 | prompt:read |
| POST | /prompts/{id}/versions | 创建新版本 | prompt:create |
| POST | /prompts/{id}/publish | 发布Prompt | prompt:update |
| POST | /prompts/{id}/test | 测试运行 | prompt:execute |

**筛选参数**: `?category=xxx&tags=tag1,tag2&status=published&page=1`

---

## 9. 知识库 `/api/knowledge`（已实现）

实际 API 路径前缀为 `/api/knowledge`（而非 `/api/knowledge-bases`），共实现 11 个端点。

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| GET | /knowledge/knowledge-bases | 知识库列表（分页） | 无 |
| POST | /knowledge/knowledge-bases | 创建知识库 | knowledge.create |
| GET | /knowledge/knowledge-bases/{kb_id} | 知识库详情 | 无 |
| PUT | /knowledge/knowledge-bases/{kb_id} | 更新知识库 | knowledge.update |
| DELETE | /knowledge/knowledge-bases/{kb_id} | 删除知识库（软删除） | knowledge.delete |
| POST | /knowledge/knowledge-bases/{kb_id}/documents/upload | 上传文档（multipart） | knowledge.upload |
| GET | /knowledge/knowledge-bases/{kb_id}/documents | 文档列表 | 无 |
| GET | /knowledge/documents/{doc_id} | 文档详情 | 无 |
| DELETE | /knowledge/documents/{doc_id} | 删除文档（软删除） | knowledge.delete |
| GET | /knowledge/documents/{doc_id}/chunks | 查看文档分块列表 | 无 |
| POST | /knowledge/knowledge-bases/{kb_id}/search | 语义检索 | 无 |

**已实现功能**（阶段4）：
- ✅ 知识库 CRUD（5个端点）
- ✅ 文档管理（4个端点）
- ✅ 分块查询（1个端点）
- ✅ 语义检索（1个端点）
- ⏳ 重新处理文档（待实现 Celery 任务）

**文档上传接口详解**：
```
POST /api/knowledge/knowledge-bases/{kb_id}/documents/upload
Content-Type: multipart/form-data

参数：
- file: 上传的文件（支持 pdf/docx/txt/md）
- 返回：文档记录（状态为 pending）
```

**语义检索接口详解**：
```
POST /api/knowledge/knowledge-bases/{kb_id}/search
Content-Type: application/json

请求体：
{
  "query": "查询文本",
  "top_k": 5,
  "score_threshold": 0.7
}

返回：
[
  {
    "chunk_id": 123,
    "doc_id": 45,
    "content": "相关文档片段...",
    "score": 0.85
  }
]
```

---

## 10. 工作流 `/api/workflows`

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| GET | /workflows | 工作流列表 | workflow:read |
| POST | /workflows | 创建工作流 | workflow:create |
| GET | /workflows/{id} | 工作流详情(含节点和边) | workflow:read |
| GET | /workflows/{id}/export | 导出工作流定义 | workflow:export |
| PUT | /workflows/{id} | 更新工作流(含节点和边) | workflow:update |
| DELETE | /workflows/{id} | 删除工作流 | workflow:delete |
| POST | /workflows/{id}/publish | 发布工作流 | workflow:update |
| POST | /workflows/{id}/run | 执行工作流 | workflow:execute |
| POST | /workflows/{id}/run/stream | 执行工作流(SSE流式) | workflow:execute |
| GET | /workflows/{id}/executions | 执行记录列表 | workflow:read |
| GET | /workflows/{id}/executions/{exec_id} | 执行详情(含节点执行) | workflow:read |
| POST | /workflows/{id}/executions/{exec_id}/cancel | 取消执行 | workflow:execute |

---

## 11. Agent `/api/agent`

> 实际注册前缀为 `/agent`（`backend/app/main.py`），路径段为 `/agents/...`；
> **SSE 流式端点是 `/chat/stream`**，`/chat` 为阻塞式（一次性返回）。原文档将两者标注反了，
> 且 `/chat/block` 端点并不存在。权限为 `require_permission("agent", <action>)`。

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| GET | /agent/agents | Agent列表 | - |
| POST | /agent/agents | 创建Agent | agent.create |
| GET | /agent/agents/tool-catalog | 可授权给 Agent 的插件候选目录 | - |
| GET | /agent/agents/{agent_id} | Agent详情 | - |
| PUT | /agent/agents/{agent_id} | 更新Agent | agent.update |
| DELETE | /agent/agents/{agent_id} | 删除Agent | agent.delete |
| POST | /agent/conversations | 创建对话 | agent.chat |
| GET | /agent/agents/{agent_id}/conversations | 某 Agent 的对话列表 | - |
| GET | /agent/conversations/{conversation_id} | 对话详情 | - |
| PUT | /agent/conversations/{conversation_id} | 更新对话 | agent.chat |
| DELETE | /agent/conversations/{conversation_id} | 删除对话 | agent.chat |
| POST | /agent/agents/{agent_id}/chat | 发起对话（阻塞模式，一次性返回） | agent.chat |
| POST | /agent/agents/{agent_id}/chat/stream | 发起对话（**SSE 流式**） | agent.chat |

> **未实现**：原文档中的 `GET /agents/{id}/conversations/{conv_id}/messages`
> （消息历史）端点不存在；对话详情接口已包含消息内容。

#### 11.1 SSE 事件流（`/chat/stream`）

事件格式为标准 `event: <type>\ndata: <json>\n\n`。

| 事件 | 载荷 | 说明 |
|------|------|------|
| `message` | `{ "content": string }` | 正文增量片段 |
| `citations` | `{ "citations": Citation[], "tool"?: string, "query"?: string }` | 知识库工具**召回后、正文生成前**推送，增量（仅本次新增的编号）。可能多次出现 |
| `done` | `{ "content", "conversation_id", "prompt_tokens", "completion_tokens", "total_tokens", "citations": Citation[] }` | 结束；`citations` 为**全量**冗余，用于前端丢包兜底 |
| `error` | `{ "error": string, "error_code"?: string }` | 失败 |

`Citation` 字段见 [citation-traceability.md](citation-traceability.md)。未识别的事件名前端**跳过而不报错**，
故新增事件类型对旧版前端无破坏（`citations` 亦如此）。

#### 11.2 消息对象新增字段

`GET /agent/conversations/{conversation_id}` 返回的每条 `messages[]` 增加
`citations: Citation[] | null`（无引用为 `null`）——刷新页面后角标与来源卡片据此复原。

---

## 12. 插件 `/api/plugins`

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| GET | /plugins | 插件列表(公共+租户私有) | plugin:read |
| POST | /plugins | 创建插件 | plugin:create |
| GET | /plugins/{id} | 插件详情(含端点) | plugin:read |
| PUT | /plugins/{id} | 更新插件 | plugin:update |
| DELETE | /plugins/{id} | 删除插件 | plugin:delete |
| POST | /plugins/{id}/test | 测试插件 | plugin:execute |
| GET | /plugins/{id}/endpoints | 插件端点列表 | plugin:read |
| POST | /plugins/{id}/endpoints | 添加端点 | plugin:create |
| PUT | /plugins/{id}/endpoints/{ep_id} | 更新端点 | plugin:update |
| DELETE | /plugins/{id}/endpoints/{ep_id} | 删除端点 | plugin:delete |
| GET | /plugins/{id}/config | 获取插件配置 | plugin:read |
| PUT | /plugins/{id}/config | 更新插件配置 | plugin:update |

**列表筛选参数**：`GET /plugins?source_type=http&status=active&include_public=true`

- `source_type` 接入方式（插件怎么接进来）：`http` / `mcp` / `skill`。

创建/更新时的 `source_type` 受枚举校验，非法值返回 `422`。
其语义与使用场景见 [plugin-types.md](plugin-types.md)。

> **M2.0 变更**：原 `plugin_type`（能力形态：tool / connector / processor）已移除，
> 列表过滤参数与创建/更新字段均不再接受该字段；插件形态由 `source_type` 单一维度承载。
> 移除理由见 [plugin-types.md](plugin-types.md) §8。

---

## 13. 审计与监控 `/api/audit`

> 实际共实现 4 个端点；原文档中的 `token-usage` / `model-stats` 名称有误，
> `export` 端点未实现。

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| GET | /audit/logs | 审计日志查询(分页+筛选) | require_permission |
| GET | /audit/model-calls | 模型调用记录 | require_permission |
| GET | /audit/token-stats | Token 用量统计 | require_permission |
| GET | /audit/dashboard | 监控仪表盘数据 | require_permission |
| GET | /audit/export | 导出审计数据 | ❌ 未实现 |

**审计日志筛选参数**: `?action=login&resource_type=user&user_id=1&start_date=2024-01-01&end_date=2024-12-31&page=1&page_size=20`

---

## 14. 平台租户开通 `/api/admin`（仅平台管理员）

> 平台接口使用 `require_platform_permission(...)`：`is_platform_admin` 只证明平台身份，
> 具体能力仍需明确的 platform permission；通过平台守卫后才允许显式跨租户查询上下文。

平台管理员只负责创建租户并开通首位租户管理员；不提供租户列表/详情、配额、删除或平台公共模型管理接口。

### 租户创建 `/api/admin/tenants`

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /admin/tenants | 原子创建租户、内置角色和指定的首位管理员账号 |

请求字段包括租户名称、描述、管理员邮箱和初始密码。新账号被绑定为租户 owner，并获得该租户的 `tenant_admin` 角色。

**Dashboard响应示例**:
```json
{
  "total_tokens_today": 150000,
  "total_cost_today": 2.5,
  "total_requests_today": 320,
  "active_users_today": 15,
  "model_usage": [
    {"model_id": 1, "model_name": "gpt-4o", "tokens": 100000, "requests": 200, "cost": 2.0}
  ],
  "daily_trend": [
    {"date": "2024-01-15", "tokens": 150000, "requests": 320, "cost": 2.5}
  ]
}
```
