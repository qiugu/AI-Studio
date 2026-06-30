# AI-Studio 数据库模型设计

## 1. 租户 & 用户 & 权限（已有基础，需扩展）

### tenants 租户表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | BigInteger PK | 主键 |
| name | String(255) | 租户名称 |
| description | String(500) | 租户描述 |
| plan | String(50) | 套餐计划(free/pro/enterprise) |
| max_users | Integer | 最大用户数 |
| max_models | Integer | 最大模型数 |
| status | Boolean | 状态（True=启用，False=禁用，禁用后租户所有请求返回 403） |
| deleted_at | DateTime | 软删除时间（NULL=正常，非空=已注销，触发异步数据清理） |
| is_system_init | Boolean | 是否为系统初始化时创建的默认租户 |
| created_at | DateTime | 创建时间 |
| updated_at | DateTime | 更新时间 |

### users 用户表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | BigInteger PK | 主键 |
| tenant_id | BigInteger FK | 所属租户 |
| email | String(255) UNIQUE | 邮箱 |
| password_hash | String(255) | 密码哈希 |
| nickname | String(255) | 昵称 |
| avatar | String(255) | 头像URL |
| status | Boolean | 状态(True=启用) |
| last_login_at | DateTime | 最后登录时间 |
| created_at | DateTime | 创建时间 |
| updated_at | DateTime | 更新时间 |
| deleted_at | DateTime | 软删除时间 |
| is_platform_admin | Boolean | 是否为平台超级管理员（不受租户 RBAC 约束，可跨租户操作） |

**关系**: users ↔ roles (多对多, 通过 user_roles)

### roles 角色表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | BigInteger PK | 主键 |
| tenant_id | BigInteger FK | 所属租户 |
| name | String(100) | 角色名称 |
| code | String(100) UNIQUE | 角色编码 |
| description | String(500) | 角色描述 |
| status | Boolean | 状态 |
| created_at | DateTime | 创建时间 |

**关系**: roles ↔ permissions (多对多, 通过 role_permissions)

### permissions 权限表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | BigInteger PK | 主键 |
| resource | String(100) | 资源标识(user/model/prompt/kb/workflow/agent/plugin/audit) |
| action | String(100) | 操作标识(create/read/update/delete/execute/export) |
| description | String(255) | 权限描述 |
| created_at | DateTime | 创建时间 |

### user_roles 用户角色关联表

| 字段 | 类型 | 说明 |
|------|------|------|
| user_id | BigInteger FK PK | 用户ID |
| role_id | BigInteger FK PK | 角色ID |

### role_permissions 角色权限关联表

| 字段 | 类型 | 说明 |
|------|------|------|
| role_id | BigInteger FK PK | 角色ID |
| permission_id | BigInteger FK PK | 权限ID |

### api_keys API密钥表（新增）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | BigInteger PK | 主键 |
| tenant_id | BigInteger FK | 所属租户 |
| user_id | BigInteger FK | 所属用户 |
| name | String(255) | 密钥名称 |
| key_hash | String(255) | 密钥哈希 |
| key_prefix | String(20) | 密钥前缀(用于辨识) |
| expires_at | DateTime | 过期时间 |
| last_used_at | DateTime | 最后使用时间 |
| status | Boolean | 状态 |
| created_at | DateTime | 创建时间 |

### 资源可见性规则

平台存在两种可见性范围的资源：**租户私有**（默认）和**平台公共**（`tenant_id IS NULL`）。

| 资源表 | 支持公共资源 | 规则 |
|--------|------------|------|
| `ai_models` | 是 | `tenant_id IS NULL` 表示平台预置模型，所有租户只读可用；写操作仅限 `is_platform_admin=true` |
| `plugins` | 是 | `tenant_id IS NULL` + `is_public=true` 表示平台公共插件，租户可安装使用 |
| `prompts` | 否 | 仅租户私有，不跨租户共享 |
| `knowledge_bases` | 否 | 仅租户私有 |
| `workflows` | 否 | 仅租户私有 |
| `agents` | 否 | 仅租户私有 |

**查询规则**: 支持公共资源的表，列表查询默认返回 `tenant_id = current_tenant OR tenant_id IS NULL`；创建/修改/删除公共资源仅限 `is_platform_admin=true` 的用户。

---

## 2. AI模型管理（新增）

### ai_providers AI供应商表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | BigInteger PK | 主键 |
| tenant_id | BigInteger FK | 所属租户 |
| name | String(255) | 供应商显示名称 |
| provider_type | String(50) | 供应商类型(openai/anthropic/azure/zhipu/baichuan/ollama/custom) |
| api_base_url | String(500) | API基础URL |
| api_key_encrypted | Text | 加密存储的API Key |
| config | JSON | 额外配置(请求头、超时等) |
| status | Boolean | 状态 |
| created_at | DateTime | 创建时间 |
| updated_at | DateTime | 更新时间 |

### ai_models AI模型配置表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | BigInteger PK | 主键 |
| tenant_id | BigInteger FK | 所属租户 |
| provider_id | BigInteger FK | 所属供应商 |
| name | String(255) | 模型标识(gpt-4o, claude-3-sonnet等) |
| display_name | String(255) | 显示名称 |
| model_type | String(50) | 模型类型(chat/embedding/image/audio/rerank) |
| config | JSON | 模型配置(temperature范围、上下文长度等) |
| unit_price_input | Decimal(10,6) | 输入单价(每千token美元) |
| unit_price_output | Decimal(10,6) | 输出单价(每千token美元) |
| max_context_tokens | Integer | 最大上下文token数 |
| max_output_tokens | Integer | 最大输出token数 |
| status | Boolean | 状态 |
| created_at | DateTime | 创建时间 |
| updated_at | DateTime | 更新时间 |

---

## 3. Prompt管理（新增）

### prompts Prompt模板表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | BigInteger PK | 主键 |
| tenant_id | BigInteger FK | 所属租户 |
| name | String(255) | 模板名称 |
| description | Text | 模板描述 |
| model_id | BigInteger FK | 关联模型(可选) |
| category | String(100) | 分类标签 |
| tags | JSON | 标签列表 |
| current_version | Integer | 当前版本号 |
| status | String(20) | 状态(draft/published/archived) |
| created_by | BigInteger FK | 创建人 |
| created_at | DateTime | 创建时间 |
| updated_at | DateTime | 更新时间 |

### prompt_versions Prompt版本表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | BigInteger PK | 主键 |
| prompt_id | BigInteger FK | 所属Prompt |
| version | Integer | 版本号 |
| content | Text | Prompt内容 |
| variables | JSON | 变量定义(名称、类型、默认值、描述) |
| change_note | String(500) | 变更说明 |
| created_by | BigInteger FK | 创建人 |
| created_at | DateTime | 创建时间 |

**唯一约束**: (prompt_id, version)

### prompt_test_logs Prompt测试日志表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | BigInteger PK | 主键 |
| prompt_version_id | BigInteger FK | 测试的Prompt版本 |
| user_id | BigInteger FK | 测试人 |
| input_variables | JSON | 输入变量值 |
| output | Text | 模型输出内容 |
| model_id | BigInteger FK | 使用的模型 |
| prompt_tokens | Integer | 输入token数 |
| completion_tokens | Integer | 输出token数 |
| latency_ms | Integer | 响应耗时(毫秒) |
| status | String(20) | 状态(success/failed) |
| error_message | Text | 错误信息 |
| created_at | DateTime | 创建时间 |

---

## 4. 知识库（已实现）

### knowledge_bases 知识库表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | BigInteger PK | 主键 |
| tenant_id | BigInteger FK | 所属租户 |
| name | String(255) | 知识库名称 |
| description | Text | 描述 |
| embedding_model | String(100) | 使用的向量模型（如 text-embedding-3-small） |
| document_count | Integer | 文档数量（冗余字段） |
| chunk_count | Integer | 总分块数（冗余字段） |
| created_at | DateTime | 创建时间 |
| updated_at | DateTime | 更新时间 |
| deleted_at | DateTime | 软删除时间 |

**说明**：实际实现中 `embedding_model` 为字符串类型，存储模型名称而非外键引用。每个知识库对应一个独立的 Qdrant Collection（命名规则：`kb_{kb_id}`）。

### knowledge_documents 知识库文档表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | BigInteger PK | 主键 |
| tenant_id | BigInteger FK | 所属租户 |
| kb_id | BigInteger FK | 所属知识库 |
| file_name | String(255) | 文件名 |
| file_type | String(20) | 文件类型（pdf/docx/txt/md） |
| file_size | BigInteger | 文件大小（字节） |
| file_url | String(500) | 文件存储URL（如 S3） |
| original_content | Text | 解析后的原始文本内容 |
| chunk_count | Integer | 分块数量 |
| status | Enum | 状态（pending/processing/completed/failed） |
| error_message | Text | 处理失败时的错误信息 |
| processed_at | DateTime | 处理完成时间 |
| created_at | DateTime | 创建时间 |
| updated_at | DateTime | 更新时间 |
| deleted_at | DateTime | 软删除时间 |

**状态流转**：
- `pending` → 初始状态，文档已上传但未处理
- `processing` → Celery 任务正在处理（解析 → 分块 → 向量化）
- `completed` → 处理成功，向量已存入 Qdrant
- `failed` → 处理失败，`error_message` 字段记录错误详情

### knowledge_chunks 知识库分块表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | BigInteger PK | 主键 |
| tenant_id | BigInteger FK | 所属租户 |
| kb_id | BigInteger FK | 所属知识库（冗余，加速查询） |
| doc_id | BigInteger FK | 所属文档 |
| content | Text | 分块文本内容 |
| chunk_index | Integer | 分块序号（从 0 开始） |
| source_page | Integer | PDF 页码（可选） |
| vector_id | String(36) | Qdrant 中的 Point UUID |
| created_at | DateTime | 创建时间 |
| updated_at | DateTime | 更新时间 |
| deleted_at | DateTime | 软删除时间 |

**索引**：`(kb_id)`、`(doc_id)`、`(vector_id)`（唯一）

**Qdrant Collection 配置**：

```
Collection命名规则: kb_{kb_id}  (每个知识库独立Collection)

Collection配置:
  vectors:
    size: 根据模型动态调整（OpenAI text-embedding-3-small 为 1536，BAAI bge-m3 为 1024）
    distance: Cosine    # 余弦相似度
  hnsw_config:
    m: 16               # HNSW邻居数
    ef_construct: 100   # 构建时搜索宽度

Point结构:
  id: UUID              # 对应 knowledge_chunks.vector_id
  vector: [float...]    # embedding向量
  payload:
    chunk_id: int       # 关联MySQL的chunk主键
    doc_id: int         # 文档ID
    kb_id: int          # 知识库ID
    tenant_id: int      # 租户ID（用于批量清理）
    content: str        # 分块文本内容（直接存储，避免二次查库）
    source_page: int    # 页码（可选）
```

**已实现功能**（阶段4）：
- ✅ 知识库 CRUD（创建、列表、详情、更新、删除）
- ✅ 文档上传（支持 PDF/Word/Markdown/TXT）
- ✅ 文档状态追踪（pending → processing → completed/failed）
- ✅ 向量检索（语义搜索，返回相似度评分）
- ⏳ Celery 异步任务（待完成，用于自动处理文档）

**权限**：
- `knowledge.create` - 创建知识库
- `knowledge.read` - 查看知识库
- `knowledge.update` - 编辑知识库
- `knowledge.delete` - 删除知识库和文档
- `knowledge.upload` - 上传文档

---

## 5. 工作流引擎（新增）

### workflows 工作流表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | BigInteger PK | 主键 |
| tenant_id | BigInteger FK | 所属租户 |
| name | String(255) | 工作流名称 |
| description | Text | 描述 |
| icon | String(50) | 图标标识 |
| version | Integer | 版本号 |
| status | String(20) | 状态(draft/published/archived) |
| created_by | BigInteger FK | 创建人 |
| created_at | DateTime | 创建时间 |
| updated_at | DateTime | 更新时间 |

### workflow_nodes 工作流节点表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | BigInteger PK | 主键 |
| workflow_id | BigInteger FK | 所属工作流 |
| node_type | String(50) | 节点类型(start/end/llm/condition/code/tool/input/output/knowledge/loop/subflow/variable) |
| name | String(255) | 节点名称 |
| config | JSON | 节点配置(模型ID、Prompt、条件表达式等) |
| position | JSON | 画布位置({x, y}) |
| created_at | DateTime | 创建时间 |

### workflow_edges 工作流连线表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | BigInteger PK | 主键 |
| workflow_id | BigInteger FK | 所属工作流 |
| source_id | BigInteger FK | 源节点ID |
| target_id | BigInteger FK | 目标节点ID |
| source_handle | String(50) | 源端口标识(条件分支用) |
| target_handle | String(50) | 目标端口标识 |
| condition | JSON | 条件表达式(条件节点用) |
| label | String(100) | 连线标签 |
| created_at | DateTime | 创建时间 |

### workflow_executions 工作流执行记录表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | BigInteger PK | 主键 |
| workflow_id | BigInteger FK | 工作流ID |
| tenant_id | BigInteger FK | 租户ID |
| status | String(20) | 状态(pending/running/success/failed/cancelled) |
| inputs | JSON | 输入参数 |
| outputs | JSON | 输出结果 |
| error_message | Text | 错误信息 |
| total_tokens | Integer | 消耗总token |
| started_at | DateTime | 开始时间 |
| completed_at | DateTime | 完成时间 |
| created_by | BigInteger FK | 执行人 |
| created_at | DateTime | 创建时间 |

### node_executions 节点执行记录表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | BigInteger PK | 主键 |
| execution_id | BigInteger FK | 所属工作流执行 |
| node_id | BigInteger FK | 节点ID |
| node_type | String(50) | 节点类型 |
| status | String(20) | 状态(pending/running/success/failed/skipped) |
| inputs | JSON | 节点输入 |
| outputs | JSON | 节点输出 |
| tokens_used | Integer | token消耗 |
| latency_ms | Integer | 执行耗时 |
| error_message | Text | 错误信息 |
| started_at | DateTime | 开始时间 |
| completed_at | DateTime | 完成时间 |

---

## 6. Agent系统（新增）

### agents Agent表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | BigInteger PK | 主键 |
| tenant_id | BigInteger FK | 所属租户 |
| name | String(255) | Agent名称 |
| description | Text | 描述 |
| avatar | String(500) | 头像图标 |
| system_prompt | Text | 系统Prompt |
| model_id | BigInteger FK | 使用的模型 |
| temperature | Float | 温度参数 |
| max_tokens | Integer | 最大输出token |
| response_mode | String(20) | 响应模式(stream/block) |
| knowledge_ids | JSON | 关联知识库ID列表 |
| status | String(20) | 状态(draft/published/archived) |
| created_by | BigInteger FK | 创建人 |
| created_at | DateTime | 创建时间 |
| updated_at | DateTime | 更新时间 |

### agent_tools Agent工具关联表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | BigInteger PK | 主键 |
| agent_id | BigInteger FK | Agent ID |
| tool_type | String(50) | 工具类型(function/knowledge/api/workflow/plugin) |
| name | String(255) | 工具名称 |
| description | String(500) | 工具描述 |
| config | JSON | 工具配置(OpenAI function calling schema) |
| enabled | Boolean | 是否启用 |
| created_at | DateTime | 创建时间 |

### conversations 对话会话表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | BigInteger PK | 主键 |
| agent_id | BigInteger FK | Agent ID |
| user_id | BigInteger FK | 用户ID |
| tenant_id | BigInteger FK | 租户ID |
| title | String(255) | 对话标题 |
| summary | Text | 对话摘要 |
| total_tokens | Integer | 总消耗token |
| created_at | DateTime | 创建时间 |
| updated_at | DateTime | 更新时间 |

### messages 对话消息表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | BigInteger PK | 主键 |
| conversation_id | BigInteger FK | 所属对话 |
| role | String(20) | 角色(user/assistant/system/tool) |
| content | Text | 消息内容 |
| tokens | Integer | 消耗token数 |
| metadata | JSON | 元数据(工具调用信息、引用来源等) |
| parent_id | BigInteger FK | 父消息ID(分支对话) |
| created_at | DateTime | 创建时间 |

---

## 7. 插件系统（新增）

### plugins 插件表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | BigInteger PK | 主键 |
| tenant_id | BigInteger FK | 所属租户(公共插件为NULL) |
| name | String(255) | 插件名称 |
| plugin_type | String(50) | 插件类型(tool/provider/processor/connector) |
| version | String(20) | 版本号 |
| description | Text | 描述 |
| config_schema | JSON | 配置Schema(JSON Schema定义) |
| icon | String(100) | 图标 |
| author | String(255) | 作者 |
| homepage_url | String(500) | 主页链接 |
| api_spec | JSON | OpenAPI/Swagger规范 |
| status | String(20) | 状态(active/disabled/pending_review) |
| is_public | Boolean | 是否公共插件 |
| created_at | DateTime | 创建时间 |
| updated_at | DateTime | 更新时间 |

### plugin_configs 插件配置表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | BigInteger PK | 主键 |
| plugin_id | BigInteger FK | 插件ID |
| tenant_id | BigInteger FK | 租户ID(租户级配置) |
| name | String(255) | 配置名称 |
| value | JSON | 配置值(按config_schema校验) |
| created_at | DateTime | 创建时间 |
| updated_at | DateTime | 更新时间 |

**唯一约束**: (plugin_id, tenant_id, name)

### plugin_endpoints 插件端点表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | BigInteger PK | 主键 |
| plugin_id | BigInteger FK | 插件ID |
| endpoint | String(500) | API端点路径 |
| method | String(10) | HTTP方法(GET/POST/PUT/DELETE) |
| headers | JSON | 请求头 |
| request_body_schema | JSON | 请求体Schema |
| response_schema | JSON | 响应Schema |
| description | Text | 端点描述 |
| created_at | DateTime | 创建时间 |

---

## 8. 审计与监控（新增）

### audit_logs 审计日志表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | BigInteger PK | 主键 |
| tenant_id | BigInteger FK | 租户ID(索引) |
| user_id | BigInteger FK | 操作用户 |
| action | String(50) | 操作类型(create/read/update/delete/execute/login/export/import) |
| resource_type | String(50) | 资源类型(user/role/model/provider/prompt/kb/workflow/agent/plugin/api_key) |
| resource_id | BigInteger | 资源ID |
| details | JSON | 操作详情 |
| ip_address | String(50) | IP地址 |
| user_agent | String(500) | User-Agent |
| created_at | DateTime | 创建时间(索引) |

**索引**: (tenant_id, created_at), (user_id), (resource_type, resource_id)

### token_usages Token用量统计表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | BigInteger PK | 主键 |
| tenant_id | BigInteger FK | 租户ID(索引) |
| user_id | BigInteger FK | 用户ID |
| model_id | BigInteger FK | 模型ID |
| agent_id | BigInteger FK | Agent ID(可空) |
| workflow_execution_id | BigInteger FK | 工作流执行ID(可空) |
| prompt_test_id | BigInteger FK | Prompt测试ID(可空) |
| source_type | String(20) | 来源类型(agent/workflow/prompt/api) |
| source_id | BigInteger | 来源ID |
| prompt_tokens | Integer | 输入token数 |
| completion_tokens | Integer | 输出token数 |
| total_tokens | Integer | 总token数 |
| cost | Decimal(10,6) | 费用(美元) |
| created_at | DateTime | 创建时间(索引) |

**索引**: (tenant_id, created_at), (model_id, created_at), (user_id, created_at)

### model_call_logs 模型调用日志表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | BigInteger PK | 主键 |
| tenant_id | BigInteger FK | 租户ID |
| user_id | BigInteger FK | 用户ID |
| model_id | BigInteger FK | 模型ID |
| source_type | String(20) | 来源类型(prompt/agent/workflow/api) |
| source_id | BigInteger | 来源ID |
| request | JSON | 请求内容 |
| response | JSON | 响应内容 |
| prompt_tokens | Integer | 输入token |
| completion_tokens | Integer | 输出token |
| total_tokens | Integer | 总token |
| latency_ms | Integer | 响应耗时 |
| status | String(20) | 状态(success/failed/timeout) |
| error_message | Text | 错误信息 |
| created_at | DateTime | 创建时间 |

**索引**: (tenant_id, created_at), (model_id, created_at)