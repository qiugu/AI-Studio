# RBAC 租户权限设置实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**目标：** 将 AI-Studio 的租户权限从“路由级 resource/action RBAC + 特殊管理员布尔值”升级为“租户隔离、RBAC 授权、资源级策略、审计可追溯”四层模型，在不破坏现有租户数据的前提下支持最小权限、拒绝默认、职责分离和后续多租户成员关系扩展。

**架构：** 保留 FastAPI/SQLAlchemy 现有技术栈，在应用内建立统一的 Policy Enforcement Point（PEP）和 Policy Decision Point（PDP）。PDP 先判断已验证的租户上下文与角色权限，再判断资源归属、所有者、共享关系和资源状态；全局 ORM 租户过滤器继续作为纵深防御，但不再承担“谁能执行哪个动作”的完整授权职责。平台权限独立于租户角色，暂不引入 OPA/Cedar；当服务拆分或策略复杂度超过应用内 PDP 承受范围时再评估外部策略引擎。

**技术栈：** Python 3.11+、FastAPI、SQLAlchemy 2.0、Alembic、Pydantic v2、React 19、TypeScript、Zustand、pytest。

## 全局约束

- 所有未明确允许的请求默认拒绝；前端只做体验优化，服务端是唯一授权事实来源。
- 认证、授权和租户隔离是三个独立控制面：登录成功不等于拥有资源权限，也不等于可以访问其他租户。
- 用户权限只能通过角色获得；禁止新增直接 user_permissions 旁路。
- 租户上下文必须由服务端验证的 membership 产生；JWT 中的 tid 只能作为请求上下文提示，不能单独作为授权证明。
- 平台管理员不再通过“跳过全局租户过滤器”获得无限业务能力；平台操作必须拥有明确的 platform 权限，并默认拒绝进入租户业务接口。
- 角色、权限、成员关系、资源共享和权限变更都要可审计；高风险操作必须记录 actor、tenant、target、decision、reason 和 request_id。
- 所有 ORM SELECT、UPDATE、DELETE、Core SQL、Celery 任务和向量检索回表路径都必须明确租户边界；不能只依赖查询时的单一钩子。
- 不在第一阶段引入任意角色继承、任意用户自定义策略表达式或外部 PDP；先建立稳定权限目录和可测试的应用内授权接口。
- 任何迁移都必须支持存量租户和回滚/双读窗口，不能用破坏性重建覆盖现有 users.tenant_id、user_roles、roles、permissions 数据。

## 社区实践转译为本项目的设计结论

- NIST RBAC 的核心是“用户通过角色获得权限，并可增加角色约束”；因此权限应沉淀在角色，不直接散落在用户记录上。
- OWASP 要求拒绝默认、每次请求服务端校验、最小权限，并同时覆盖功能级、数据级和字段级授权；所以路由守卫只能是第一层，Service 必须执行资源级判断。
- AWS 的多租户实践明确区分“授权”和“租户隔离”；本项目的 tenant scope 过滤器应继续存在，但必须与 PDP 组合使用，不能把二者混为一个 is_platform_admin 开关。
- 当授权规则跨越多个服务或需要独立治理时，才将应用内 PDP 替换/旁路到 OPA/Cedar；当前单体架构先使用可替换的接口，避免过早引入外部基础设施。

参考：

- NIST RBAC FAQ：https://csrc.nist.gov/Projects/role-based-access-control/faqs
- OWASP Authorization Cheat Sheet：https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html
- OWASP Authorization Patterns：https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Patterns_Cheat_Sheet.html
- AWS SaaS Tenant Isolation：https://docs.aws.amazon.com/whitepapers/latest/saas-architecture-fundamentals/tenant-isolation.html
- AWS SaaS Authorization Guidance：https://docs.aws.amazon.com/prescriptive-guidance/latest/saas-multitenant-api-access-authorization/introduction.html

## 目标权限模型

### 1. 四层决策模型

一次授权决定固定按以下顺序执行，任何一层失败都返回拒绝：

1. 身份层：token 有效、用户未删除、账号启用、邮箱/登录状态符合策略。
2. 租户层：请求 tenant context 已解析，用户在该租户存在有效 membership，租户启用且未删除。
3. RBAC 层：用户的有效租户角色包含目标 permission；角色必须属于同一租户且未停用。
4. 资源层：目标对象属于当前租户，或是明确允许的公共资源；再判断 owner、shared subject、发布状态、敏感字段和操作前置条件。

### 2. 权限标识

权限目录使用稳定的 resource.action key，resource 和 action 保留为结构化字段，后续可增加 scope 而不改变现有接口：

- 租户治理：tenant.read、tenant.settings.update、tenant.members.read、tenant.members.manage、tenant.roles.read、tenant.roles.manage、tenant.audit.read、tenant.usage.read
- AI 模型：ai_provider.read、ai_provider.manage、ai_model.read、ai_model.manage、ai_model.test
- Prompt：prompt.read、prompt.create、prompt.update、prompt.delete、prompt.publish、prompt.test
- 知识库：knowledge.read、knowledge.create、knowledge.update、knowledge.delete、knowledge.document.upload、knowledge.document.delete、knowledge.search
- Agent：agent.read、agent.create、agent.update、agent.delete、agent.publish、agent.chat、agent.tools.manage
- 工作流：workflow.read、workflow.create、workflow.update、workflow.delete、workflow.publish、workflow.execute、workflow.export
- 插件：plugin.read、plugin.install、plugin.configure、plugin.update、plugin.delete、plugin.endpoint.bind
- 平台：platform.tenant.provision、platform.permission.catalog.manage、platform.public_model.manage、platform.public_plugin.manage

权限目录由迁移/种子数据维护，租户管理员只能把已有权限绑定到角色，不能自行创建新 permission key。每个 key 必须有中文显示名、英文稳定 key、敏感级别和是否允许委派的元数据。

### 3. 角色集合

内置角色建议改为模板化角色，角色实例仍归属于租户：

- tenant_owner：租户生命周期内唯一的所有者能力；可管理管理员，但不能修改平台权限。
- tenant_admin：租户日常管理、成员、角色、租户设置、审计和用量；不自动获得跨租户能力。
- builder：Prompt、知识库、Agent、工作流的创建和编辑，不含成员/角色/审计管理。
- operator：已发布 Agent 对话、已发布工作流执行、知识库检索，不含草稿编辑。
- knowledge_manager：知识库和文档管理，不含 Agent/工作流发布。
- auditor：审计、用量、资源只读，不含执行和写操作。
- member：最小业务使用权限，默认只读、对话和执行已发布能力。

建议保留租户管理员自定义角色，但加以下约束：

- 自定义角色只能绑定本权限目录中的可委派权限。
- 不能将 platform 权限绑定到租户角色。
- 不能把 tenant.roles.manage 与 tenant.members.manage 通过自定义角色授予普通成员，除非操作者是 owner 或已具备明确的角色委派权限。
- 角色停用前必须检查存量用户；停用/删除会产生审计事件，且租户必须始终保留至少一个可用 owner/admin 路径。
- 第一阶段不实现任意 role hierarchy；如确有需要，下一阶段只允许平台预定义的继承关系。

### 4. 资源级策略

路由权限只回答“能否尝试这个动作”，资源策略回答“能否对这个对象执行动作”：

- 默认资源范围为 tenant。
- 草稿/未发布资源默认仅允许 owner 或具备资源管理权限的角色访问。
- 发布后的 Agent/Workflow 执行由 operator 或 member 的 chat/execute 权限控制；编辑、发布和删除分开授权。
- 资源共享通过显式 resource_grants 实现，禁止通过前端传入任意 tenant_id 或“猜 ID”扩大范围。
- 公共 AI 模型/插件仍使用 tenant_id IS NULL 语义，但只有平台权限可以写入/发布；租户只读/安装/配置租户级副本。
- 需要字段脱敏时在响应 Schema 或 Service 层执行，不把 API Key、密文、内部连接参数暴露给只读角色。

## 目标数据结构

### 立即兼容版本

先保留现有表并补充约束/元数据：

- users：暂保留 tenant_id，新增/统一 authz_version；is_platform_admin 进入兼容期，不再作为新增授权逻辑的入口。
- roles：保留 tenant_id、code、status、is_admin；新增 kind（builtin/custom）、template_code、is_delegable、updated_at。后续由权限集合推导管理能力，逐步移除 is_admin 依赖。
- permissions：增加唯一约束 (resource, action) 或稳定 key；新增 scope、sensitivity、is_delegable、status。
- role_permissions：保留复合主键，补充外键约束和删除策略；写入前校验 role 与 permission 的租户/平台边界。
- user_roles：保留兼容读写，所有写操作统一经过 AuthorizationService 的角色委派检查。
- audit_logs：增加 decision、permission_key、target_type、target_id、reason、request_id、metadata。

### 战略目标版本

当产品需要一个用户加入多个租户时，新增并逐步切换到：

- tenant_memberships(id, tenant_id, user_id, status, is_owner, authz_version, joined_at, removed_at)：用户与租户的关系是授权主体，不能再由 users.tenant_id 单列表达。
- membership_roles(membership_id, role_id)：角色绑定到 membership，而不是直接绑定全局用户。
- platform_role_assignments(user_id, role_id, status)：平台角色独立于租户角色。
- resource_grants(tenant_id, resource_type, resource_id, subject_type, subject_id, actions, expires_at, created_by)：显式资源共享/委派；第一阶段可只支持 role subject，第二阶段再支持 user subject。
- authorization_events 或扩展 audit_logs：记录授权变更和决策结果，支持追责与回放。

## 现有代码与目标的主要差距

- app/core/dependencies.py 目前把 is_admin 视为通用旁路；应改为调用统一 PDP，只有显式权限可以管理成员/角色。
- app/core/tenant_scope.py 当前平台管理员会跳过所有租户过滤；目标是只对经过授权的 platform query 显式打开跨租户视角，并默认 fail-closed。
- app/core/security.py 的 token 含 tid，但没有 membership 版本/会话版本；应增加租户会话和授权版本校验，角色变更后让旧 token 尽快失效。
- app/models/user.py 强制单租户；短期可保留，长期迁移到 tenant_memberships。
- app/services/role.py 目前 set_role_permissions 只校验 permission ID 存在；应校验 permission 是否可委派、是否为平台权限、是否违反角色委派边界。
- app/services/user.py 当前允许租户管理员全量替换角色；应增加“操作者能否授予目标角色”的约束和最后一个 owner/admin 保护。
- app/middleware/audit.py 只按 HTTP 方法和路径记录写操作；应记录明确的授权决定和敏感读取/拒绝事件。
- frontend/src/utils/permission.ts 和 usePermission.ts 只做展示层判断；应改为消费服务端计算的 capability snapshot，但不能把前端结果当作安全边界。

---

## 实施任务

## 当前执行状态（2026-10-14）

已完成第一阶段及资源授权/审计的基础切片：稳定权限目录、应用内 PDP/PEP、租户启用状态校验、授权版本失效、权限委派边界、平台显式权限守卫、显式跨租户查询上下文、公共模型/插件平台写入口、Agent/Workflow/Prompt/KnowledgeBase/Plugin/AIModel 资源策略、对话/消息及工作流执行父资源继承校验、角色级资源共享、owner/admin 生命周期保护、统一高风险二次认证、结构化授权审计、事务内授权 outbox、Agent/Workflow 行级 capability 返回，以及基于 `tenant + user + authz_version` 的进程内短 TTL allow 缓存。本轮已增加 tenant membership / membership_roles 的回填迁移、只读一致性校验和可关闭双写；membership 读取切换仍待脱敏副本验证。

本轮验证：RBAC/业务后端回归为 `1132 passed, 4 skipped, 1 deselected, 325 warnings`；完整 suite 另有 1 个环境依赖失败（`tests/test_embedding.py::test_embedding_client` 需要本地缓存 `BAAI/bge-base-zh-v1.5`，不涉及本轮改动）。前端 `npm run lint`、TypeScript、Vitest `27 files / 147 tests passed` 与生产构建均通过。新增跨租户完整路径矩阵、权限元数据迁移、脱敏数据库 schema/backfill/双写/rollback 演练、membership 旁路、membership 版本失效、结构化 PDP shadow 比较、membership_readiness 切换门禁、owner/membership 关系完整性门禁、active membership 无角色门禁、后台任务上下文专项、`/me` staged capability snapshot、双写前 shadow/membership 统一 fail-closed、`--require-membership-ready` 发布门禁、管理员/角色并发回归 harness、唯一管理员权限清空保护、membership 强制模式双写前 fail-closed 检查、旧 schema 缺列早返回检查和 BaseHTTPMiddleware 跨 Context 租户清理回归均通过或按环境跳过；宿主机目标库及 Compose 实际 MySQL 均已升级到 `p2_permission_metadata`，分别通过 readiness，Compose 实际库完成 536 条 shadow/membership 决策全量对比且 `mismatches=0`，并已按 `dual_write -> shadow -> membership` 顺序完成运行实例切换。生产回滚仍保留为 `MEMBERSHIP_READ_MODE=shadow|legacy`。

### Task 1：建立权限目录与授权契约

**文件：**

- Create: app/core/permissions.py
- Create: app/core/authorization_types.py
- Modify: app/models/permission.py
- Modify: app/schemas/role.py
- Create: tests/test_permission_catalog.py
- Create: alembic/versions/20261013_normalize_permission_catalog.py

**接口：**

- PermissionKey：稳定的 resource.action 常量集合。
- PermissionDefinition：包含 key/resource/action/description/scope/sensitivity/is_delegable。
- get_permission_definition(resource: str, action: str) -> PermissionDefinition：未知 key 直接抛出领域校验异常。
- is_permission_delegable(permission: Permission, actor: User, role: Role) -> bool：平台权限永不允许绑定到租户角色。

**步骤：**

- [x] 先为当前实际路由清点权限，补齐所有已使用的 knowledge/agent/workflow/ai_provider/ai_model/prompt/plugin/user/role/audit/tenant key。
- [x] 用唯一稳定 key 作为权限目录事实来源，迁移时对现有 (resource, action) 做幂等 upsert，不删除未识别的存量权限。
- [x] 增加 catalog 单测：未知 key 拒绝、platform 权限不可绑定到租户角色、敏感权限带有明确 sensitivity。
- [x] 将前端展示名称从后端权限描述或前端静态映射读取，禁止前端拼接权限 key；角色权限接口同时返回 scope、sensitivity 和 is_delegable 元数据。
- [x] 将 scope/sensitivity/is_delegable 持久化到 permissions 表；`p2_permission_metadata` 负责存量回填、重复 key 绑定归并和唯一索引。

### Task 2：实现统一 PDP/PEP

**文件：**

- Create: app/core/authorization.py
- Modify: app/core/dependencies.py
- Modify: app/core/tenant_scope.py
- Modify: app/core/exceptions.py
- Create: tests/test_authorization_service.py
- Create: tests/test_authorization_dependencies.py

**接口：**

AuthorizationService.check_permission(actor, tenant_id, resource, action, resource_obj=None) -> AuthorizationDecision

AuthorizationService.require_permission(...)

AuthorizationService.can_assign_role(actor, target_role) -> bool

AuthorizationDecision 至少包含 allowed、reason、permission_key、tenant_id、target_type、target_id，供审计使用。

**步骤：**

- [x] 将 require_permission(resource, action) 改为调用 PDP，不再单独查询 Role.is_admin 作为总开关。
- [x] 保留 require_tenant_user，但把它收敛为“有效 membership/租户上下文”检查；普通业务接口仍需显式 permission。
- [x] 将 require_tenant_admin 改为检查 tenant.members.manage、tenant.roles.manage 等明确能力；保留兼容别名一段迁移期。
- [x] 将平台守卫改为 require_platform_permission("tenant_provision") 等显式权限，默认不设置跨租户 ORM bypass。
- [x] 为拒绝决策定义统一错误码和对外安全文案；详细 reason 只进入审计，不把角色、租户或资源存在性泄露给无权用户。
- [x] 增加 fail-closed 测试：无权限、停用角色、跨租户 role、未知 permission、停用租户/平台角色访问租户业务接口均被拒绝；完整 membership 模型启用后再补 membership 状态专测。

### Task 3：强化租户上下文与身份会话

**文件：**

- Modify: app/core/security.py
- Modify: app/core/dependencies.py
- Modify: app/middleware/tenant.py
- Modify: app/models/user.py
- Create: app/models/tenant_membership.py（战略版本启用时）
- Create: app/models/platform_role_assignment.py（战略版本启用时）
- Create: tests/test_tenant_context.py
- Create: alembic/versions/20261014_add_membership_authz_version.py

**步骤：**

- [x] 短期在 token 增加 authz_version；不把完整角色/权限列表写入 JWT，每次请求以数据库中的当前状态为准。
- [x] 角色、权限、成员状态、租户停用或移除时递增 authz_version，使旧访问令牌失效。
- [x] 将 JWT tid 视为候选 tenant context，服务端通过当前用户租户归属与启用状态校验，不能仅信任 token 中的值。
- [x] 改造 tenant_scope：普通租户请求只过滤当前 tenant；平台请求只有在显式 PlatformQueryContext 下才允许跨租户查询。专门的跨租户运营读取接口及其审计接入待后续落地。
- [x] 对 Celery/CLI/迁移上下文要求显式传入 tenant context；文档处理、租户清理 Celery 任务、数据库维护 CLI 和 Alembic migration environment 均已接入显式上下文，跨租户迁移使用带审计语义的 platform maintenance scope。
- [x] 战略迁移前置：创建 tenant_memberships / membership_roles，按 users.tenant_id 回填，并提供只读一致性校验。
- [x] 在 membership_dual_write_enabled 关闭时保持旧授权读取路径不变；开启后，用户创建/角色替换/成员删除/owner 转移/角色删除会双写 membership_roles。
- [x] 完成目标数据库 readiness 校验和 shadow/membership 全量决策对比后切换 membership 读取来源；Compose 运行实例已切换为 `MEMBERSHIP_DUAL_WRITE_ENABLED=true`、`MEMBERSHIP_READ_MODE=membership`，回滚可切回 `shadow` 或 `legacy`。

### Task 4：资源级授权与共享模型

**文件：**

- Create: app/models/resource_grant.py
- Create: app/services/resource_authorization.py
- Modify: app/services/agent.py
- Modify: app/services/workflow.py
- Modify: app/services/knowledge.py
- Modify: app/services/prompt.py
- Modify: app/services/plugin.py
- Create: tests/test_resource_authorization.py

**步骤：**

- [x] 为 Agent、Workflow、Prompt 定义统一资源策略：归属租户、创建者/owner、发布状态、软删除状态、共享 grants；KnowledgeBase 已补父资源和文档继承校验；Plugin/AIModel 已补服务层 actor 校验和公共资源写保护。
- [x] 在 Agent/Workflow API 的 get/update/delete/publish/execute/chat 入口调用资源授权服务；Service 内部继续补齐 actor 传递和 worker 上下文。
- [x] 对资源 ID 查询先执行 tenant + resource 状态过滤，再执行 permission + owner/share 判断；跨租户 ID 不会通过资源授权。
- [x] 约束子资源：知识库文档、对话/消息、插件配置和工作流节点/执行均继承父资源与租户校验；WorkflowEngine 已在阻塞/流式执行前重复校验 `workflow.execute`。
- [x] resource_grants 初期只允许租户管理员/owner 授予角色级共享，支持撤销和过期；请求体不接受 tenant_id，租户由服务端上下文决定。
- [x] 对公共 AI 模型和插件继续保留 public_or_tenant_filter 语义；租户读写路由按显式权限拆分，并新增 platform.public_model_manage / platform.public_plugin_manage 平台写入口，平台授权决策进入结构化审计上下文。

### Task 5：角色委派、成员生命周期与职责分离

**文件：**

- Modify: app/services/role.py
- Modify: app/services/user.py
- Modify: app/api/role.py
- Modify: app/api/user.py
- Modify: app/schemas/role.py
- Modify: app/schemas/user.py
- Create: tests/test_role_delegation.py

**步骤：**

- [x] 角色创建/修改/绑定统一校验 is_delegable、角色类型、平台权限边界和操作者可委派权限；平台权限边界与角色权限集合均 fail-closed。
- [x] 成员停用、删除、角色替换均要求目标用户和目标角色属于当前租户；停用/删除后授权版本立即失效。
- [x] 保证租户始终有一个可用 owner/admin；删除、停用或降权最后一个管理路径时拒绝操作。
- [x] 对 tenant_owner 的转移采用当前密码二次确认、行锁/幂等事务和结构化审计事件；不能仅靠修改 owner_id 或 is_admin。
- [x] 新增授权决策已改由明确 permission 集合决定；Role.is_admin 仅保留在最后一个管理员保护和兼容展示路径，后续继续收敛。
- [x] 为高风险操作增加统一二次认证/重新输入密码配置点；owner 转移、角色权限与生命周期管理、成员降权/删除/角色替换、AI 供应商敏感凭据配置和插件租户敏感凭据变更均在 Service 层强制校验，配置开关默认 fail-closed。普通角色名称/描述、普通供应商配置、普通插件连接参数以及插件端点定义不要求当前密码；插件凭据检测按配置项名称和嵌套字段识别。

### Task 6：审计、缓存和权限变更传播

**文件：**

- Modify: app/models/audit_log.py
- Modify: app/middleware/audit.py
- Create: app/services/authorization_audit.py
- Modify: app/core/redis.py
- Create: tests/test_authorization_audit.py

**步骤：**

- [x] 授权决定和资源分享操作具备结构化审计写入服务，HTTP 审计中间件兼容写入决定字段。
- [x] 审计字段至少包含 actor user、active tenant、target resource、permission key、decision、reason、request_id、IP、user-agent、created_at。
- [x] 权限缓存只缓存短 TTL 的角色/权限快照，并以 tenant + membership/user + authz_version 为 key；角色、成员和权限变更通过版本化 key 失效旧缓存，不缓存拒绝结果。
- [x] 缓存条目过期、未命中或缓存配置关闭时回源数据库；缓存不会把旧的 allow 结果无限期继续使用。
- [x] 审计写入失败不应阻断普通读取，但高风险授权变更通过 `authorization_outbox` 在同一事务内可靠写入，支持 pending/replay 状态且敏感 metadata 自动脱敏。

### Task 7：前端能力快照与导航一致性

**文件：**

- Modify: frontend/src/types/api.ts
- Modify: frontend/src/api/auth.ts
- Modify: frontend/src/stores/auth.ts
- Modify: frontend/src/hooks/usePermission.ts
- Modify: frontend/src/utils/permission.ts
- Modify: frontend/src/components/PermissionGuard.tsx
- Modify: frontend/src/components/TenantAdminGuard.tsx
- Modify: frontend/src/components/AdminGuard.tsx
- Modify: frontend/src/components/Layout/Sidebar.tsx
- Create: frontend/src/types/authorization.ts
- Create: frontend/src/utils/permission.test.ts 的资源级展示用例

**步骤：**

- [x] 登录/当前用户响应提供角色摘要和后端计算的 capabilities；前端不从角色名或 is_admin 子串推断权限。
- [x] PermissionGuard 只负责隐藏/禁用控件；所有点击操作仍调用服务端并正确处理 401/403/租户切换失效。
- [x] 导航按 capability 显示租户治理与业务入口；平台账号不展示租户业务入口。平台专属运营导航待平台读接口落地。
- [x] 对 Agent/Workflow 资源行级操作使用服务端返回的 allowed_actions，避免在前端复制 owner/published 判断；其他资源类型待复用同一响应约定。
- [x] 角色编辑页按后端权限目录分组展示，并隐藏不可委派的 platform/未知权限；影响范围提示仍待补齐。

### Task 8：安全回归、迁移演练与上线

**文件：**

- Create: tests/integration/test_rbac_tenant_isolation.py
- Create: tests/integration/test_resource_authorization.py
- Create: scripts/verify_rbac_migration.py
- Modify: docs/database-design.md
- Modify: docs/api-design.md
- Modify: docs/core-mechanisms.md
- Modify: CLAUDE.md

**步骤：**

- [x] 新增只读 `scripts/verify_rbac_migration.py`：输出租户级用户/角色/授权/审计/outbox 统计，检测缺表、孤儿关联、跨租户角色绑定、重复权限键、非法资源授权主体和非法 outbox 状态；`--strict` 可作为迁移门禁。
- [x] 新增 `tests/integration/test_rbac_tenant_isolation.py`，覆盖跨租户 Agent/Workflow IDOR、公共模型/插件可见性、未公开公共行隐藏，以及草稿编辑/已发布执行的纵向权限边界。
- [x] 新增 `tests/integration/test_resource_authorization.py`，验证对话/消息继承 Agent 父资源的租户边界和草稿/发布状态策略。
- [x] 新增 membership 迁移回填、双写开关和一致性校验测试；迁移 head 已推进至 `p2_permission_metadata`。
- [x] 增加 `membership_read_mode=legacy|shadow|membership` 发布开关：shadow 仅记录旧/新决策差异，membership 才切换强制读取来源；默认保持 legacy。
- [x] 新增 RBAC 路径矩阵集成测试，覆盖跨租户 Agent/Workflow/Prompt/KnowledgeBase/AIModel/Plugin/用户/角色 IDOR、草稿/已发布纵向边界和租户角色写平台公共资源。
- [x] 清理前端现存 lint 阻断：`npm run lint`、`npx tsc --noEmit`、Vitest `27 files / 147 tests passed` 和 `npm run build` 均通过；后端 `compileall` 与 `git diff --check` 通过。
- [x] 构造至少两个租户、平台公共资源、两个角色和多类资源，验证 list/get/update/delete/export/execute/chat 全路径的租户隔离。
- [x] 验证横向越权：修改 URL 中的资源 ID、role ID、user ID、tenant ID、plugin endpoint ID 都不能访问其他租户。
- [x] 验证纵向越权：member 不能管理成员/角色、operator 不能编辑草稿、auditor 不能执行、builder 不能跨租户读取。
- [x] 验证公开资源：公共模型/插件按声明可见，未公开 tenant_id IS NULL 资源不可见；平台写操作不可被租户角色调用。
- [x] 验证并发边界：最后一个 admin/owner 的删除、角色停用、权限变更和 token 刷新保持约束；`tests/integration/test_rbac_concurrency.py` 在隔离 MySQL 8.4 中通过 4 项回归（含管理员权限清空与角色停用竞态，以及角色变更后 refresh token 使用最新 `authz_version`）。生产数据库仍需按同一门禁执行。
- [x] 在脱敏的 legacy-shaped SQLite 副本运行 schema/backfill/dual-read/rollback 演练；同时由只读 verifier 输出每个租户的用户、角色、membership、权限和异常统计。生产数据库仍需上线前按同一流程运行。
- [x] 上线采用 feature flag：Compose 环境已按 `dual_write=true + legacy` → `shadow` → `membership` 顺序切换；shadow smoke 返回 200 且记录结构化决策，536 条真实决策对比无 mismatch，非 legacy 启动前强制执行 `--strict --require-membership-ready`，并保留 `shadow/legacy` 回滚开关。
- [x] 通过 python -m compileall app、目标 pytest、前端 npm run lint、npm run build、git diff --check 后再发布；RBAC/业务回归 `1132 passed, 4 skipped, 1 deselected, 325 warnings`，Alembic head 为 `p2_permission_metadata`。完整回归的单项模型缓存失败已明确记录，不能替代上线前模型环境验证。

## 上线顺序与回滚

1. P0 权限目录与测试基线：不改变现有访问结果，只补齐 key、元数据和审计字段。
2. P1 PDP shadow mode：新旧守卫并行计算，仅记录不一致；修复误拒绝和漏拒绝。
3. P2 强制 RBAC：启用 deny-by-default 和角色委派约束，暂保留旧列与旧 API 兼容。
4. P3 资源级策略：先 Agent/Workflow/Knowledge，随后 Prompt/Plugin；每个模块独立 feature flag。
5. P4 多租户 membership：完成双写、回填、切换和数据校验后，再逐步废弃 users.tenant_id / user_roles 直接授权路径。
6. P5 清理兼容代码：确认审计、缓存失效、回滚窗口和跨租户测试稳定后，移除 is_admin 授权分支和平台全局 bypass。

回滚原则：任何阶段只回滚授权决策开关和读路径，不删除已迁移数据；保留新增列/表和审计事件，避免回滚后无法解释已发生的权限变更。

## 验收标准

- 任意未注册 permission 的新端点默认返回拒绝，而不是因遗漏守卫而放行。
- 租户用户无法通过 IDOR、JOIN、批量接口、Core SQL、异步任务或向量回表读取其他租户数据。
- 平台管理员只能执行显式 platform 能力；没有租户 membership 时不能访问租户业务 API。
- 角色变更、成员停用、租户停用和权限目录变更在短时间内对旧 token/缓存生效。
- 自定义角色不能获得不可委派的平台权限或越过角色委派边界。
- Agent/Workflow/Knowledge/Prompt/Plugin 的读取、编辑、发布、执行、共享、删除权限能够独立配置。
- 所有 allow/deny 的高风险授权决定可按 actor、tenant、permission、target、request_id 在审计日志中还原。
- 前端只反映后端 capability，不存在仅靠隐藏按钮就能绕过的安全路径。

## 本阶段明确不做

- 不在当前阶段引入多套外部授权引擎或把策略拆到微服务。
- 不把完整权限列表写入长期 JWT。
- 不允许租户管理员自定义新的权限动作或任意 CEL/Rego/SQL 条件。
- 不把平台管理员直接扩展为“所有租户超级用户”；如需要支持平台运营查看，另建最小只读/支持角色并逐操作审计。
- 不通过前端传入的 tenant_id、角色名称、资源名称或 URL 约定作为授权依据。
