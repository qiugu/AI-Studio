# AI-Studio 分阶段实施计划

## 概述

共8个阶段，每个阶段包含后端+前端同步开发。每阶段结束后需进行code review和基础测试。

---

## 阶段一：基础架构完善

**目标**: 补全认证/RBAC/中间件/异常处理/通用Schema，建立项目基座

### 后端任务

1. **完善配置系统**
   - 扩展 `app/core/config.py`，增加JWT、Redis、pgvector、文件上传、Celery配置项
   - 更新 `.env` 文件

2. **安全模块** `app/core/security.py`
   - JWT Token 生成/验证/刷新
   - 密码哈希(passlib + bcrypt)
   - API Key 生成与验证

3. **依赖注入** `app/core/dependencies.py`
   - `get_current_user` - 获取当前用户
   - `get_current_tenant` - 获取当前租户
   - `require_permission(resource, action)` - 权限检查装饰器
   - `get_vector_session` - pgvector session

4. **异常体系** `app/core/exceptions.py`
   - AppException基类
   - NotFoundException, UnauthorizedException, ForbiddenException, ValidationException等

5. **通用Schema** `app/schemas/common.py`
   - `ResponseBase` - 统一响应格式
   - `PaginatedResponse` - 分页响应
   - `PageParams` - 分页请求参数

6. **中间件**
   - `app/middleware/tenant.py` - 租户隔离(注入tenant_id到请求状态)
   - `app/middleware/audit.py` - 审计日志(记录写操作)
   - `app/middleware/rate_limit.py` - 限流(基于Redis)

7. **完善认证API** `app/api/auth.py`
   - 实现 login（返回 JWT）
   - 实现 register（**原子事务**: 创建租户 → 创建用户 → 初始化内置角色 `tenant_admin`/`tenant_member` → 分配 admin 角色 → 返回 JWT + tenant_info）
   - 实现 refresh（刷新 token）
   - 实现 logout（token 黑名单/Redis）

8. **完善用户服务** `app/services/user.py`
   - 修复 create_user（密码哈希）
   - create_user 前调用 `QuotaService.check_user_quota()` 检查配额
   - CRUD 操作

9. **更新模型**
   - Tenant 增加字段（description, plan, max_users, max_models, deleted_at, is_system_init）
   - User 增加字段（last_login_at, is_platform_admin）
   - Permission 增加字段（description）
   - Role 增加字段（description）

10. **新增模型**
    - `app/models/api_key.py` - API 密钥模型

11. **实现 BaseRepository 基类** `app/repositories/base.py`
    - 泛型基类，构造时绑定 tenant_id
    - `_tenant_filter()` / `_tenant_or_public_filter()` 方法
    - `get_by_id` / `list` / `count` 通用方法
    - `get_repo()` 工厂依赖函数（`app/core/dependencies.py`）

12. **实现 QuotaService** `app/services/quota.py`
    - `check_user_quota(tenant_id)` 方法
    - `check_model_quota(tenant_id)` 方法

13. **完善 TenantMiddleware** `app/middleware/tenant.py`
    - 增加租户状态校验（status=False → 403 TENANT_DISABLED）
    - 增加软删除校验（deleted_at 非空 → 403 TENANT_NOT_FOUND）
    - 白名单跳过（/auth/login、/auth/register、/auth/refresh）

14. **超级管理员守卫** `app/core/dependencies.py`
    - `require_platform_admin` 依赖函数

15. **注册中间件和路由** `app/main.py`
    - 添加中间件（TenantMiddleware, AuditMiddleware）
    - 异常处理器
    - CORS 配置

16. **生成 Alembic 迁移**

### 前端任务

1. **项目初始化**
   ```bash
   npm create vite@latest frontend -- --template react-ts
   cd frontend
   npm install antd @ant-design/icons @ant-design/x zustand react-router-dom axios dayjs
   npm install -D @types/node
   ```

2. **基础配置**
   - `vite.config.ts` - 代理配置、路径别名
   - `tsconfig.json` - 路径别名
   - `.eslintrc.cjs` + `.prettierrc`

3. **API客户端**
   - `src/api/client.ts` - axios实例+拦截器(token注入、错误处理、刷新token)
   - `src/api/auth.ts` - 认证API

4. **状态管理**
   - `src/stores/auth.ts` - 认证状态(login/logout/token/user)
   - `src/stores/app.ts` - 全局状态(侧边栏/主题)

5. **路由配置**
   - `src/App.tsx` - 路由定义、路由守卫

6. **全局样式**
   - `src/styles/global.css` - Ant Design主题变量

7. **布局组件**
   - `src/components/Layout/AppLayout.tsx`
   - `src/components/Layout/Sidebar.tsx`
   - `src/components/Layout/Header.tsx`

8. **工具函数**
   - `src/utils/auth.ts` - token存取
   - `src/utils/request.ts`

9. **登录页面**
   - `src/pages/Login/index.tsx`

10. **通用组件**
    - `src/components/PermissionGuard.tsx`
    - `src/components/Pagination.tsx`

---

## 阶段二：AI模型管理

**目标**: 实现AI供应商和模型的完整CRUD，集成LangChain

### 后端任务

1. **新增模型**
   - `app/models/ai_provider.py`
   - `app/models/ai_model.py`
   - 更新 `app/models/__init__.py`

2. **API Key加密** `app/utils/encryption.py`
   - Fernet加密/解密

3. **供应商服务** `app/services/ai_provider.py`
   - CRUD + API Key加密存储
   - 连通性测试

4. **模型服务** `app/services/ai_model.py`
   - CRUD
   - 模型调用测试

5. **LLM客户端** `app/utils/llm.py`
   - LangChain集成，动态构建ChatModel
   - 支持OpenAI/Anthropic/Azure/Ollama等

6. **配额集成**
   - `AIModelService.create_model()` 前调用 `QuotaService.check_model_quota()`

7. **API路由**
   - `app/api/ai_provider.py`
   - `app/api/ai_model.py`（`GET /ai-models` 支持 `include_public` 参数，查询时使用 `_tenant_or_public_filter()`）

8. **注册路由** 更新 `app/main.py`

9. **Alembic迁移**

### 前端任务

1. **类型定义**
   - `src/types/ai-model.ts`

2. **API层**
   - `src/api/ai-model.ts`

3. **供应商管理页面**
   - `src/pages/AIModels/ProviderList.tsx` - 供应商卡片列表，状态指示灯
   - `src/pages/AIModels/ProviderForm.tsx` - 供应商创建/编辑表单

4. **模型管理页面**
   - `src/pages/AIModels/ModelList.tsx` - 模型表格(类型筛选、供应商筛选)
   - `src/pages/AIModels/ModelForm.tsx` - 模型创建/编辑表单

5. **连接测试弹窗组件**

---

## 阶段三：Prompt管理

**目标**: Prompt CRUD + 版本管理 + 变量渲染 + 测试运行

### 后端任务

1. **新增模型**
   - `app/models/prompt.py`
   - `app/models/prompt_version.py`
   - `app/models/prompt_test_log.py`

2. **Prompt服务** `app/services/prompt.py`
   - CRUD + 版本管理
   - 变量渲染(get_template + render)
   - 测试运行(调用LLM)

3. **API路由** `app/api/prompt.py`

4. **Alembic迁移**

### 前端任务

1. **类型定义** `src/types/prompt.ts`

2. **API层** `src/api/prompt.ts`

3. **Prompt列表** `src/pages/Prompts/PromptList.tsx`
   - 表格(分类筛选、标签筛选、状态筛选)
   - 创建/删除操作

4. **Prompt编辑器** `src/pages/Prompts/PromptEditor.tsx`
   - 左右分栏: 变量列表 | Prompt内容区
   - 变量高亮显示
   - Markdown预览

5. **Prompt详情** `src/pages/Prompts/PromptDetail.tsx`
   - 版本列表
   - 版本对比(Diff视图)
   - 测试运行面板(输入变量 → 结果展示)

6. **代码编辑器组件** `src/components/CodeEditor.tsx`
   - 集成Monaco Editor

---

## 阶段四：知识库

**目标**: KB CRUD + 文档上传/解析/分块 + pgvector集成 + 检索API

### 后端任务

1. **pgvector连接** `app/core/vector_db.py`
   - PostgreSQL连接管理

2. **新增模型**
   - `app/models/knowledge_base.py`
   - `app/models/knowledge_document.py`
   - `app/models/knowledge_chunk.py`

3. **向量表DDL** (pgvector)
   - knowledge_vectors 表创建

4. **文档解析** `app/utils/document.py`
   - PDF/Word/TXT/MD解析
   - RecursiveCharacterTextSplitter分块

5. **Embedding客户端** `app/utils/embedding.py`

6. **Celery配置** `app/core/celery_app.py`
   - 文档处理异步任务

7. **知识库服务** `app/services/knowledge.py`
   - KB CRUD
   - 文档上传 → 触发Celery任务
   - 向量化流程
   - 语义检索

8. **知识库处理** `app/services/knowledge_processor.py`
   - Celery任务: 文档解析 → 分块 → Embedding → 存入pgvector

9. **API路由** `app/api/knowledge.py`

10. **文件上传中间件/依赖**

11. **Alembic迁移** + pgvector建表

### 前端任务

1. **类型定义** `src/types/knowledge.ts`

2. **API层** `src/api/knowledge.ts`

3. **知识库列表** `src/pages/Knowledge/KnowledgeList.tsx`
   - 卡片式展示(文档数、分块数、状态)

4. **知识库详情** `src/pages/Knowledge/KnowledgeDetail.tsx`
   - 文档列表 + 上传区
   - 文档状态指示(pending → processing → completed/failed)
   - 分块查看

5. **文档上传组件** `src/pages/Knowledge/DocumentUpload.tsx`
   - Ant Design Upload组件 + 拖拽上传
   - 进度条 + 状态反馈

6. **检索测试面板**
   - 输入查询 → 返回相关文档片段

---

## 阶段五：Agent系统

**目标**: Agent CRUD + 工具绑定 + LangChain ReAct Agent + 对话 + SSE流式

### 后端任务

1. **新增模型**
   - `app/models/agent.py`
   - `app/models/agent_tool.py`
   - `app/models/conversation.py`
   - `app/models/message.py`

2. **Agent服务** `app/services/agent.py`
   - Agent CRUD
   - 工具构建(knowledge/api/function/workflow/plugin)
   - LangChain Agent构建
   - ReAct循环执行

3. **对话服务** `app/services/conversation.py`
   - 对话创建/列表/详情
   - 消息记录

4. **SSE流式** `app/api/agent.py`
   - SSE流式对话端点
   - 阻塞式对话端点

5. **Token统计**
   - 每次LLM调用后记录token_usage

6. **API路由** `app/api/agent.py`

7. **Alembic迁移**

### 前端任务

1. **类型定义** `src/types/agent.ts`

2. **API层** `src/api/agent.ts`

3. **SSE Hook** `src/hooks/useSSE.ts`

4. **Agent列表** `src/pages/Agents/AgentList.tsx`
   - 卡片式列表(Avatar、名称、描述、模型)

5. **Agent创建/编辑** `src/pages/Agents/AgentForm.tsx`
   - 基本信息设置
   - System Prompt编辑
   - 工具绑定(从知识库/插件/工作流中选择)
   - 参数设置(temperature, max_tokens)

6. **Agent对话** `src/pages/Agents/AgentChat.tsx`
   - 基于@ant-design/x的聊天界面
   - SSE流式渲染
   - 工具调用展示(折叠面板)
   - 对话历史侧边栏
   - Markdown + 代码高亮渲染

7. **聊消息组件** `src/components/ChatMessage.tsx`
8. **聊天输入组件** `src/components/ChatInput.tsx`

---

## 阶段六：工作流引擎

**目标**: Workflow CRUD + DAG执行引擎 + React Flow可视化编辑器

### 后端任务

1. **新增模型**
   - `app/models/workflow.py`
   - `app/models/workflow_node.py`
   - `app/models/workflow_edge.py`
   - `app/models/workflow_execution.py`
   - `app/models/node_execution.py`

2. **工作流服务** `app/services/workflow.py`
   - Workflow CRUD (含节点和边的批量保存)
   - 发布/归档

3. **工作流引擎** `app/services/workflow_engine.py`
   - DAG构建与拓扑排序
   - 节点执行器分发(LLM/Condition/Knowledge/Code/Tool/Loop)
   - 上下文传递
   - 错误处理与重试

4. **节点执行器实现**
   - `LLMNode` - 调用LLM
   - `ConditionNode` - 条件判断路由
   - `KnowledgeNode` - 向量检索
   - `CodeNode` - 沙盒执行(受限Python)
   - `ToolNode` - 调用Agent工具
   - `LoopNode` - 循环/迭代
   - `InputNode` / `OutputNode` - 输入输出

5. **执行API** (含SSE流式)

6. **API路由** `app/api/workflow.py`

7. **Alembic迁移**

### 前端任务

1. **类型定义** `src/types/workflow.ts`

2. **API层** `src/api/workflow.ts`

3. **工作流列表** `src/pages/Workflows/WorkflowList.tsx`

4. **工作流编辑器** `src/pages/Workflows/WorkflowEditor.tsx` ★核心页面★
   - React Flow画布
   - 左侧节点类型面板
   - 拖拽添加节点
   - 节点连线
   - 右侧节点配置面板(动态表单)
   - 保存/发布操作
   - 节点类型:
     - 开始/结束节点
     - LLM节点(选择模型、设置Prompt)
     - 条件节点(条件表达式)
     - 知识库节点(选择知识库、检索参数)
     - 代码节点(代码编辑器)
     - 工具节点(选择工具)
     - 循环节点
     - 变量节点

5. **执行面板** `src/pages/Workflows/WorkflowExecution.tsx`
   - 输入参数表单
   - 执行日志
   - 节点执行状态展示
   - 结果展示

---

## 阶段七：插件系统

**目标**: 插件注册/配置 + OpenAPI规范解析 + 插件调用

### 后端任务

1. **新增模型**
   - `app/models/plugin.py`
   - `app/models/plugin_config.py`
   - `app/models/plugin_endpoint.py`

2. **插件服务** `app/services/plugin.py`
   - 插件CRUD
   - OpenAPI规范解析
   - 插件端点管理
   - 插件配置(按租户)
   - 插件连通性测试

3. **插件沙盒执行** `app/utils/plugin_executor.py`
   - HTTP请求封装
   - 超时控制
   - 错误处理

4. **API路由** `app/api/plugin.py`

5. **Agent集成** - 更新Agent Tool构建，支持plugin类型

6. **Alembic迁移**

### 前端任务

1. **类型定义** `src/types/plugin.ts`

2. **API层** `src/api/plugin.ts`

3. **插件列表** `src/pages/Plugins/PluginList.tsx`
   - 公共插件 + 租户私有插件
   - 安装/启用/禁用

4. **插件配置** `src/pages/Plugins/PluginConfig.tsx`
   - 基于JSON Schema的动态表单
   - 端点列表展示
   - 测试按钮

---

## 阶段八：监控审计 & 仪表盘

**目标**: 审计日志中间件 + Token统计 + Dashboard

### 后端任务

1. **新增模型**
   - `app/models/audit_log.py`
   - `app/models/token_usage.py`
   - `app/models/model_call_log.py`

2. **审计服务** `app/services/audit.py`
   - 审计日志查询(分页+筛选)
   - Token用量统计(按时间/按模型/按用户)
   - 模型调用统计
   - Dashboard聚合数据

3. **完善审计中间件** `app/middleware/audit.py`
   - 自动记录写操作

4. **完善LLM调用日志**
   - 在 `LLMClient.ainvoke` 中自动记录到 model_call_logs

5. **用户管理API** `app/api/user.py`, `app/api/role.py`
   - 用户 CRUD + 角色分配
   - 角色 CRUD + 权限分配

6. **审计API路由** `app/api/audit.py`

7. **平台管理员 API** `app/api/admin.py`
   - 所有接口使用 `require_platform_admin` 守卫
   - 租户列表/详情/创建/状态变更/配额修改/注销（`DELETE` 触发软删除）
   - 平台公共模型 CRUD（`tenant_id=NULL` 的 ai_models）

8. **租户数据清理 Celery 任务** `app/services/tenant_cleanup.py`
   - 删除 pgvector 中该租户的向量数据
   - 删除文件存储中该租户的上传文件
   - 级联软删除: users / ai_providers / knowledge_bases / workflows / agents / conversations
   - 保留: audit_logs / token_usages（合规 & 计费依据）

9. **Alembic迁移**

### 前端任务

1. **类型定义** `src/types/api.ts` (补充审计类型)

2. **API层** `src/api/audit.ts`

3. **Dashboard仪表盘** `src/pages/Dashboard/index.tsx`
   - Token用量趋势图(Ant Design Charts)
   - 模型调用统计柱状图
   - 活跃用户数
   - 快捷入口

4. **用户管理** `src/pages/System/Users.tsx`
   - 用户列表(筛选/搜索)
   - 创建/编辑用户
   - 角色分配

5. **角色权限** `src/pages/System/Roles.tsx`
   - 角色列表
   - 权限矩阵勾选

6. **审计日志** `src/pages/System/AuditLogs.tsx`
   - 高级筛选（时间/操作/资源/用户）
   - 数据表格
   - 导出 CSV

7. **TenantSettings 页面** `src/pages/System/TenantSettings.tsx`
   - 当前租户基本信息展示与编辑
   - 成员列表与角色管理
   - 配额使用情况（用户数/模型数进度条展示）

8. **Admin 页面**（is_platform_admin 专属）
   - `src/pages/Admin/TenantList.tsx` - 租户列表（状态徽标/套餐标签/用量摘要/快速禁用）
   - `src/pages/Admin/TenantDetail.tsx` - 租户详情（配额修改/注销危险操作区）
   - `src/components/AdminGuard.tsx` - 超级管理员路由守卫

9. **更新路由配置** `src/App.tsx`
   - 新增 `/system/tenant` 路由（TenantSettings）
   - 新增 `/admin/*` 路由组（AdminGuard 包裹）

---

## 每阶段检查清单

每个阶段完成后需验证:

- [ ] Alembic迁移运行成功
- [ ] API接口可正常调用(用Postman/curl测试)
- [ ] 前后端联调通过
- [ ] RBAC权限正确拦截
- [ ] 审计日志正确记录写操作
- [ ] 租户数据隔离（所有 Repository 均继承 BaseRepository，tenant_id 过滤自动生效）
- [ ] 新建用户/模型时配额限制生效（超出返回 429 QUOTA_EXCEEDED）
- [ ] 禁用租户后该租户所有 API 返回 403 TENANT_DISABLED
- [ ] 代码 review 无明显问题