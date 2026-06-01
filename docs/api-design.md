# AI-Studio API路由设计

所有API前缀: `/api`

通用响应格式:
```json
{
  "code": 0,
  "message": "success",
  "data": {}
}
```

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
| POST | /auth/register | 注册（同时创建租户 + 初始 admin 用户，返回 JWT） |
| POST | /auth/refresh | 刷新Token |
| POST | /auth/logout | 登出 |
| GET | /auth/me | 获取当前用户信息 |

**注册流程说明**:
- 请求体: `{ tenant_name, email, password, plan? }`
- 服务端原子操作:
  1. 创建 `tenants` 记录（plan 默认 `free`，max_users=10，max_models=5）
  2. 创建 `users` 记录，绑定 tenant_id，密码 bcrypt 哈希
  3. 为该租户初始化内置角色: `tenant_admin`（全部权限）、`tenant_member`（只读权限）
  4. 将新用户分配 `tenant_admin` 角色
  5. 返回 `{ access_token, refresh_token, user_info, tenant_info }`
- 以上步骤在同一数据库事务中完成，任一失败全部回滚

---

## 2. 用户管理 `/api/users`

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| GET | /users | 用户列表(分页) | user:read |
| GET | /users/me | 当前用户详情 | - |
| PUT | /users/me | 更新当前用户信息 | - |
| PUT | /users/me/password | 修改密码 | - |
| PUT | /users/me/avatar | 上传头像 | - |
| GET | /users/{id} | 用户详情 | user:read |
| PUT | /users/{id} | 更新用户 | user:update |
| DELETE | /users/{id} | 删除用户(软删除) | user:delete |
| PUT | /users/{id}/status | 启用/禁用用户 | user:update |
| PUT | /users/{id}/roles | 设置用户角色 | user:update |

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

## 4. 租户管理 `/api/tenants`

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| GET | /tenants/current | 当前租户信息 | - |
| PUT | /tenants/current | 更新租户信息 | tenant:update |
| GET | /tenants/current/members | 租户成员列表 | tenant:read |
| PUT | /tenants/current/members/{user_id}/role | 修改成员角色 | tenant:update |

---

## 5. API密钥 `/api/api-keys`

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| GET | /api-keys | 密钥列表 | api_key:read |
| POST | /api-keys | 创建密钥(返回明文key) | api_key:create |
| DELETE | /api-keys/{id} | 删除密钥 | api_key:delete |
| PUT | /api-keys/{id}/status | 启用/禁用密钥 | api_key:update |

---

## 6. AI供应商 `/api/ai-providers`

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| GET | /ai-providers | 供应商列表 | provider:read |
| POST | /ai-providers | 创建供应商 | provider:create |
| GET | /ai-providers/{id} | 供应商详情 | provider:read |
| PUT | /ai-providers/{id} | 更新供应商 | provider:update |
| DELETE | /ai-providers/{id} | 删除供应商 | provider:delete |
| POST | /ai-providers/{id}/test | 测试连通性 | provider:execute |

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

## 9. 知识库 `/api/knowledge-bases`

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| GET | /knowledge-bases | 知识库列表 | kb:read |
| POST | /knowledge-bases | 创建知识库 | kb:create |
| GET | /knowledge-bases/{id} | 知识库详情 | kb:read |
| PUT | /knowledge-bases/{id} | 更新知识库 | kb:update |
| DELETE | /knowledge-bases/{id} | 删除知识库 | kb:delete |
| POST | /knowledge-bases/{id}/documents | 上传文档(multipart) | kb:update |
| GET | /knowledge-bases/{id}/documents | 文档列表 | kb:read |
| GET | /knowledge-bases/{id}/documents/{doc_id} | 文档详情 | kb:read |
| DELETE | /knowledge-bases/{id}/documents/{doc_id} | 删除文档 | kb:update |
| POST | /knowledge-bases/{id}/documents/{doc_id}/reprocess | 重新处理文档 | kb:execute |
| POST | /knowledge-bases/{id}/search | 知识库语义检索 | kb:execute |
| GET | /knowledge-bases/{id}/documents/{doc_id}/chunks | 查看文档分块 | kb:read |

---

## 10. 工作流 `/api/workflows`

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| GET | /workflows | 工作流列表 | workflow:read |
| POST | /workflows | 创建工作流 | workflow:create |
| GET | /workflows/{id} | 工作流详情(含节点和边) | workflow:read |
| PUT | /workflows/{id} | 更新工作流(含节点和边) | workflow:update |
| DELETE | /workflows/{id} | 删除工作流 | workflow:delete |
| POST | /workflows/{id}/publish | 发布工作流 | workflow:update |
| POST | /workflows/{id}/run | 执行工作流 | workflow:execute |
| POST | /workflows/{id}/run/stream | 执行工作流(SSE流式) | workflow:execute |
| GET | /workflows/{id}/executions | 执行记录列表 | workflow:read |
| GET | /workflows/{id}/executions/{exec_id} | 执行详情(含节点执行) | workflow:read |
| POST | /workflows/{id}/executions/{exec_id}/cancel | 取消执行 | workflow:execute |

---

## 11. Agent `/api/agents`

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| GET | /agents | Agent列表 | agent:read |
| POST | /agents | 创建Agent | agent:create |
| GET | /agents/{id} | Agent详情 | agent:read |
| PUT | /agents/{id} | 更新Agent | agent:update |
| DELETE | /agents/{id} | 删除Agent | agent:delete |
| POST | /agents/{id}/chat | 发起对话(SSE流式) | agent:execute |
| POST | /agents/{id}/chat/block | 发起对话(阻塞模式) | agent:execute |
| GET | /agents/{id}/conversations | 对话列表 | agent:read |
| GET | /agents/{id}/conversations/{conv_id} | 对话详情 | agent:read |
| GET | /agents/{id}/conversations/{conv_id}/messages | 消息历史 | agent:read |
| DELETE | /agents/{id}/conversations/{conv_id} | 删除对话 | agent:delete |

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

---

## 13. 审计与监控 `/api/audit`

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| GET | /audit/logs | 审计日志查询(分页+筛选) | audit:read |
| GET | /audit/token-usage | Token用量统计 | audit:read |
| GET | /audit/model-stats | 模型调用统计 | audit:read |
| GET | /audit/dashboard | 监控仪表盘数据 | audit:read |
| GET | /audit/export | 导出审计数据 | audit:export |

**审计日志筛选参数**: `?action=login&resource_type=user&user_id=1&start_date=2024-01-01&end_date=2024-12-31&page=1&page_size=20`

---

## 14. 平台管理 `/api/admin`（仅平台超级管理员）

> 所有接口均需 `users.is_platform_admin = true`，通过 `require_platform_admin` 依赖守卫鉴权，**不走普通 RBAC 权限表**。

### 租户管理 `/api/admin/tenants`

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /admin/tenants | 租户列表（分页，支持 status/plan 筛选） |
| POST | /admin/tenants | 手动创建租户（指定 plan/配额，适用企业客户） |
| GET | /admin/tenants/{id} | 租户详情（含成员数、用量统计） |
| PUT | /admin/tenants/{id}/status | 启用/禁用租户 |
| PUT | /admin/tenants/{id}/plan | 变更套餐及配额（max_users/max_models） |
| DELETE | /admin/tenants/{id} | 注销租户（软删除，触发 Celery 异步清理任务） |
| GET | /admin/tenants/{id}/stats | 租户用量统计（token 消耗/用户数/调用次数） |

### 平台公共模型管理 `/api/admin/ai-models`

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /admin/ai-models | 平台公共模型列表（`tenant_id IS NULL`） |
| POST | /admin/ai-models | 创建平台公共模型（所有租户只读可用） |
| PUT | /admin/ai-models/{id} | 更新平台公共模型 |
| DELETE | /admin/ai-models/{id} | 删除平台公共模型 |

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