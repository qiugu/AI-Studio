# 插件使用流程梳理与合理性评估

> 评审范围：AI-Studio 插件系统（Phase 7）从「插件创建」到「Agent 运行时调用」的完整链路。
> 评审方式：源码走查（后端 API / Service / Policy / Executor，前端列表页 / 配置页 / Agent 表单）+ 单元测试实跑。
> 结论口径：以当前代码实际行为为准，不以设计文档的声明为准；两者不一致处已单独标注。

---

## 0. 结论摘要

**整体方向正确。插件模块自身闭环扎实，但存在四类结构性问题：一是「插件 ↔ Agent」之间未闭合（3 处 P1），二是配置层缺少明确的写入契约（4 处 P1-C），三是端点层 schema 声明了但未接线（1 处 P1-C），四是能力模型只能表达 HTTP 接入（覆盖面问题）。**

| 结论 | 说明 |
|------|------|
| 架构方向合理 | 「设计期授权为主控 + 运行时门禁为兜底」的四层结构，控制点位置正确；两维度正交分类清晰；fail-closed 一致。 |
| **P1 · 存在问题** | 工具授权面只覆盖 `plugin` 一类，Agent 表单提交时整表替换 `agent_tools`，导致非插件工具（knowledge / api / function / workflow）在 UI 编辑保存时被**静默清空**。 |
| **P1 · 存在问题** | 插件凭据（`api_key`）明文入库、明文经接口回显；同项目内 `AIProvider` 已用 Fernet 加密，标准不统一。 |
| **P1 · 存在问题** | 运行时门禁缺少 `source_type` 判据，与设计期判据不对称；插件接入方式被改为 `mcp`/`skill` 后，既有绑定仍按 HTTP 执行（fail-open）。 |
| 流程可用但有断层 | 插件管理（admin-only）与插件授权（任意登录用户）角色错位；插件与 Agent 之间缺少双向导航；插件「存在」与「对本租户可用」未解耦。 |
| **配置层缺少写入契约** | 配置项只能新增/覆盖**无法删除**、`config_schema` 的 required 不生效且后端从不校验、凭据明文存取、测试按路径取端点会选错。详见 [§6](#6-插件配置流程专项)。 |
| **能力模型覆盖面过窄（结构性）** | 端点层与执行器均为 **HTTP 专有**：本地 MCP 服务无 `base_url`、无路径动词、能力需运行时发现，**即便二期补上 MCP 客户端也无法录入**。详见 [§7](#7-能力模型的覆盖面诊断与改造建议待评审)。 |
| 验证结果 | M1（§3.1 / §3.2 / §3.3 / P1-C1 / P1-C4 / P1-C11）与 M2.0（移除 `plugin_type`）已实施并通过测试：后端全量 **596 passed**；前端 `tsc --noEmit` 通过、`pluginMeta`+`agentToolBinding` **26 例通过**。详见 [§8](#8-m1--m20-实施记录已落地)。 |
| **P1 · 曾存在的问题（已修复）** | 「Agent 绑定工具后对话」这条路径此前**从未跑通**：文本 ReAct 模板缺 `{tool_names}` 直接崩、单入参 `Tool` 无法承载结构化参数、流式取不到逐字内容。示例插件是第一个绑定工具的场景，四条缺陷同时暴露。详见 [§8.7](#87-带工具对话链路的缺陷修复2026-09-15已落地)。 |

---

## 1. 流程全景

插件从「注册」到「被模型调用」共 4 个阶段、13 个步骤：

```
【阶段 A · 平台/租户准备插件】（admin-only）
  A1  创建插件（名称 / 能力形态 / 接入方式 / OpenAPI 规范 / 配置 Schema）
      └─ 提供 api_spec 时自动解析 paths 生成端点
  A2  配置租户凭据（base_url / api_key / api_key_header / headers）
  A3  维护端点（手动增删改 或 从 OpenAPI 导入）
  A4  连通性测试（选端点=真实调用；不选端点=探测 base_url）
  A5  启停状态切换（active / disabled）

【阶段 B · 授权给 Agent】（任意登录用户，走 Agent 表单）
  B1  打开 Agent 创建/编辑页的「工具能力」区块
  B2  目录来自 GET /agent/agents/tool-catalog（服务端裁剪）
  B3  以「插件 + 端点」为粒度勾选；破坏性端点默认隐藏 + 二次确认
  B4  保存 → _validate_tool_bindings fail-closed 校验 → 写入 agent_tools

【阶段 C · 运行时调用】
  C1  对话触发 _build_langchain_tools 逐条构造
  C2  三道运行时门禁（显式端点 / status=active / 破坏性放行）
  C3  取租户配置 → 包装为 LangChain Tool（name ASCII 安全）
  C4  模型调用 → execute_plugin_call → 路径参数编码 → SSRF 校验 → httpx 请求

【阶段 D · 变更与运维】
  D1  停用插件（运行时跳过）
  D2  删除插件（级联删端点与配置，绑定不清理）
```

---

## 2. 逐阶段实现核对

### 2.1 阶段 A · 插件准备

| 步骤 | 入口 | 后端实现 | 核对结果 |
|------|------|---------|---------|
| A1 创建 | `PluginList.tsx:113` → `POST /plugins` | `PluginService.create`（`services/plugin.py:161`） | 一致。`api_spec` 存在时调用 `_sync_endpoints_from_spec` 自动建端点 |
| A2 凭据 | `PluginConfig.tsx:257` → `PUT /plugins/{id}/config` | `PluginService.update_config`（`services/plugin.py:358`） | 一致，但**明文存储**（见 §3.2） |
| A3 端点 | `PluginConfig.tsx:323/385` | `add_endpoint` / `import_endpoints_from_spec` | 一致。`plugin_endpoints` 无 `(plugin_id, method, endpoint)` 唯一约束，重复端点可入库 |
| A4 测试 | `PluginList.tsx:179`、`PluginConfig.tsx:405` | `PluginService.test`（`services/plugin.py:386`） | 一致。指定端点走真实调用，否则探测 `base_url` |
| A5 启停 | `PluginList.tsx:169` | `PluginService.update`（`services/plugin.py:187`） | **公共插件无法在 UI 启停**（见 §3.4） |

**裁剪条件的一致性**：候选目录（`list_bindable_for_agent`，`services/plugin.py:101`）与写入校验（`check_plugin_bindable`，`core/plugin_policy.py:108`）共用同一判据，条件为「本租户或公共 + `active` + `source_type=http` + 端点 ≥ 1」。这一处设计正确，避免了「选得到却存不下」的口径漂移。

### 2.2 阶段 B · 授权给 Agent

- 授权单位是「插件 + 端点」，`selectionKey = pluginId::endpointId`（`agentToolBinding.ts:37`）。
- 破坏性动词（`DELETE`/`PUT`/`PATCH`）默认隐藏，勾选时 `Modal.confirm` 二次确认，落库写入 `allow_destructive: true`（`AgentForm.tsx:161`、`agentToolBinding.ts:131`）——**把「勾选动作」本身当作一次显式授权**，使后端门禁保持约束力。这一处设计正确。
- 工具名走 ASCII 安全化，中文插件名回退 `plugin-{id 前 8 位}`（`agentToolBinding.ts:67`），符合 OpenAI function name 约束。
- 目录加载失败时禁止提交（`AgentForm.tsx:102/463`），避免以空目录重建工具清单。
- 写入校验 fail-closed，先校验后删旧工具（`services/agent.py:244`）。

### 2.3 阶段 C · 运行时调用

`_build_langchain_tools`（`services/agent.py:504-607`）依次执行：

| 序 | 门禁 | 位置 | 不通过时 |
|----|------|------|---------|
| 1 | 必须显式给出 `endpoint_id` / `endpoint` | `agent.py:514` | 跳过 + 告警（不取首个端点） |
| 2 | `plugin.status == active` | `agent.py:530` | 跳过 + 告警 |
| 3 | 破坏性动词需 `allow_destructive: true` | `agent.py:554` | 跳过 + 告警 |

之后 `execute_plugin_call`（`utils/plugin_executor.py:77`）执行：解析 `base_url`（租户配置优先于 OpenAPI `servers`）→ 路径参数替换并 URL 编码 → `assert_outbound_url_allowed` SSRF 校验（在 `urljoin` 之后，防 `//host` 改写）→ `httpx` 请求（`follow_redirects=False`）。

**门禁 2 的缺口**：`check_plugin_bindable` 含 `source_type in BINDABLE_SOURCE_TYPES`，但运行时只调用 `check_plugin_status_gate` + `check_plugin_method_gate`，**没有 source_type 判据**（见 §3.3）。

### 2.4 阶段 D · 变更与运维

- 停用插件：运行时门禁 2 生效，能力即时失能。设计正确。
- 删除插件：`PluginService.delete`（`services/plugin.py:205`）级联清理 `plugin_endpoints` 与 `plugin_configs`，但**不检查、不清理 `agent_tools` 引用**，删除确认框也未展示受影响 Agent 数量（见 §3.5）。
- 失效授权的补偿：Agent 编辑页通过 `missingSelectionKeys` 提示（`AgentForm.tsx:434`），运行时跳过并告警。属**事后补偿**，非事前拦截。

---

## 3. 问题清单

### 3.1 [P1] UI 编辑 Agent 会静默清空非插件类工具

**证据链**

| 位置 | 行为 |
|------|------|
| `AgentForm.tsx:200` | 提交载荷 `tools = selectionsToToolPayload(selectedKeys, catalog)` |
| `agentToolBinding.ts:120` | 载荷中 `tool_type` 恒为 `'plugin'` |
| `services/agent.py:241-256` | `if data.tools is not None:` → `delete_by_agent` 硬删 → 全量重建 |
| `repositories/agent.py:56` | `delete_by_agent` 为物理删除（`.delete()`） |

**触发路径**：任何含 `knowledge` / `api` / `function` / `workflow` 工具的 Agent → 用 UI 打开编辑页 → 不改工具直接保存 → 非插件工具全部丢失，且无任何提示。

**影响**：已有 Agent 的知识库检索能力会在一次无关的编辑操作中被移除；由于 `AgentForm` 也不渲染这些类型的工具，「什么都没选」在界面上看不出异常，用户无法察觉。

**修复建议（择一，推荐第 2 项）**

1. 前端：`loadAgent` 时缓存原始工具数组，提交时仅替换 `tool_type === 'plugin'` 的条目，其余原样回传；
2. 后端：`update_agent` 改为「仅重建 `plugin` 类条目」，非插件类保持不动 —— 防御所有客户端，是更根本的修法。

---

### 3.2 [P1] 插件凭据明文存储与明文回显

**证据**

- `models/plugin.py:77`：`PluginConfig.value` 为 `JSON` 列，`update_config`（`services/plugin.py:371`）直接写入原始值。
- 对比 `models/ai_provider.py:20`：`api_key_encrypted` 为 `Text`，写入前经 `app/utils/encryption.py` 的 Fernet 加密、读取时解密。
- `GET /plugins/{id}/config`（`api/plugin.py:206`）将 `value` 原样返回；前端 `PluginConfig.tsx:171` 的 `Password` 控件仅是 UI 层遮挡，明文仍在响应体中。

**影响**：`api_key` / `token` 类凭据明文落库、明文出网（接口 / 代理日志 / 数据库备份均可获取）。与项目内既有加密标准不一致，属**安全基线倒退**。

**修复建议**

1. 复用 `AIProvider` 的加密通道：对配置值中的敏感键加密存储；
2. 敏感键判定沿用前端已有规则（`PluginConfig.tsx:155` 的 `/key|secret|token|password/i`）并下沉到后端，或在 `config_schema` 中约定 `format: password`；
3. 读取接口返回掩码 + `has_api_key` 布尔（对齐 `schemas/ai_provider.py:48` 的做法）；
4. 更新语义改为「留空表示不覆盖」，避免掩码值被回写覆盖真实凭据。

---

### 3.3 [P1] 运行时门禁缺少 `source_type` 判据，存在 fail-open 路径

**证据**

| 判据 | 设计期 | 运行时 |
|------|--------|--------|
| status | `check_plugin_bindable` ✅ | `check_plugin_status_gate` ✅ |
| **source_type** | `check_plugin_bindable` ✅ | **无** ❌ |
| endpoint 显式指定 | `binding_rejection_reason` ✅ | `has_explicit_endpoint_ref` ✅ |
| 破坏性动词 | `binding_rejection_reason` ✅ | `check_plugin_method_gate` ✅ |

**触发路径**：Agent 已授权插件 P（`source_type=http`）→ 管理员将 P 的 `source_type` 改为 `mcp` → P 从候选目录消失（用户视角「已不可选」）→ 但 `agent_tools` 中的绑定仍在，运行时门禁不检查 `source_type`，**仍按 HTTP 调用**。

**影响**：管理员的「停用该接入方式」意图未生效；用户看到的现象是「目录里已经没有了，却还在被调用」，与 `plugin_policy` 注释中「disabled 必须立即全局失能」的原则相矛盾。

**修复建议**

1. 运行时增加 `source_type` 门禁，直接复用 `BINDABLE_SOURCE_TYPES`（保证两处判据完全对称，一条常量同时约束两端）；
2. 或在 `PluginService.update` 中禁止改动「已被 Agent 绑定」的插件的 `source_type`（变更需先解绑）。

---

### 3.4 [P2] 公共插件在 UI 中既不可启停也不可编辑

**证据**：`PluginList.tsx:276` 定义 `isPublic = record.tenant_id === null`：

- `:288` 编辑按钮 `disabled={isPublic}`；
- `:262` 状态列的 `Switch` 仅在 `record.tenant_id !== null` 时渲染；
- `:313` 删除按钮 `disabled={isPublic}`。

而后端 `PluginService.update`（`services/plugin.py:189`）明确允许平台管理员更新公共插件。

**影响**：平台管理员**无法通过 UI 停用或修改已创建的公共插件**（只能经由 API）。公共插件一旦建错，界面内无补救路径。

**修复建议**：按 `isPlatformAdmin` 而非 `tenant_id === null` 决定按钮可用性；公共插件对非平台管理员保持只读。

---

### 3.5 [P2] 删除插件不展示影响面，Agent 能力静默失效

**证据**：`PluginService.delete`（`services/plugin.py:205`）无引用检查；`PluginList.tsx:304` 的确认框文案仅为「确认删除此插件？」。

**影响**：一次删除可能让 N 个 Agent 的能力失效，且失效在**运行期**才以日志告警形式暴露，用户侧表现为「Agent 突然不调用工具了」。

**修复建议**：删除前查询 `agent_tools` 中的引用，在确认框中列出受影响 Agent 数量与名称。

---

### 3.6 [P2] 权限模型与文档不一致，且粒度过粗

**证据**

- 代码：`api/plugin.py:20` 整个 router 挂 `require_tenant_admin`（平台管理员或角色 code 含 `admin`）。
- 文档：`docs/api-design.md:300-311` 声明 `plugin:read` / `plugin:create` / `plugin:update` / `plugin:delete` / `plugin:execute` 五级权限。

**影响**：其一，普通租户成员访问 `GET /plugins` 会得到 403，与文档不符；其二，「只读查看插件列表」与「修改凭据、执行任意端点」未做权限分离，租户管理员一人持有全部能力。

**修复建议**：若保留 admin-only，需更正 `api-design.md`；长期建议拆分为「配置类（读写凭据、增删插件）」与「使用类（查看列表、测试连通性）」。

---

### 3.7 [P2] 流程断层：角色、导航与配置粒度

| 断层 | 现状 | 影响 |
|------|------|------|
| 角色断层 | 插件管理为 admin-only，但插件授权发生在任意登录用户可访问的 Agent 表单 | 普通成员能看到目录中的插件，却无权配置其 `base_url` / `api_key`；若管理员未配好，用户只能看到调用失败，且**目录中不体现「配置是否就绪」** |
| 导航断层 | 插件详情页不显示「哪些 Agent 使用了它」；Agent 页也不链接回插件 | 变更前无法评估影响面，只能靠经验判断 |
| 配置粒度 | `_load_config_dict(plugin_id)`（`services/plugin.py:334`）按「租户 + 插件」取配置 | 同一租户所有 Agent 共享同一份凭据，无法为不同 Agent 配置不同账号（SaaS 类插件场景受限） |
| 可用性粒度 | 公共插件对所有租户可见即用（`docs/plugin-types.md §8` 已列为未实现项） | 无法「只对指定租户开放」 |

---

### 3.8 [P2] 其余实现细节

| # | 问题 | 证据 | 影响 |
|---|------|------|------|
| 1 | 前端列表无 `plugin_type` / `source_type` / `status` 过滤 | `PluginList.tsx:69` 硬编码 `page_size: 200`，而后端 `list` 已支持三个过滤参数 | 插件数 > 200 时列表被截断且无分页信号；后端已具备的过滤能力未暴露 |
| 2 | 列表页「测试」失败时无详情展示 | `PluginList.tsx:417` Drawer 仅在 `testResult !== null` 时打开，而失败抛异常走 toast | 用户只看到一句错误提示，看不到失败原因细节 |
| 3 | `PluginService.update` 无法置空字段 | `services/plugin.py:199` 使用 `exclude_none=True` | 清空 `description` / `api_spec` 不可行 |
| 4 | `mcp` / `skill` 可创建但不可用 | `source_type` 枚举允许创建，执行器未落地、候选目录排除 | 用户创建后无法绑定、无法测试；当前仅靠前端 Tooltip 提示 |
| 5 | 端点无唯一约束 | `models/plugin.py:86` 无 `UniqueConstraint` | 手动新增可产生重复端点，候选目录出现重复项 |
| 6 | 测试接口权限等价于插件写权限 | `POST /plugins/{id}/test` 走同一 admin 守卫，且可执行 `DELETE` / `PUT` 端点 | 属管理员调试能力，可接受；权限拆分时需一并设计 |
| 7 | 调用参数无 Schema 校验 | `execute_plugin_call` 未使用 `endpoint.request_body_schema` | `request_body_schema` 字段已存在但未生效 |
| 8 | 插件调用无审计 / 无配额 | `middleware/audit.py:14` 仅记录 API 层的写操作；Agent 运行时的插件调用不产生审计记录 | 无法追溯「哪个 Agent 在何时调用了哪个外部系统」；无法按租户/插件限流 |
| 9 | 工作流无法使用插件 | `workflow_engine.py:447` `_execute_tool_node` 返回占位字符串 | 若对外宣导「插件能力可复用」，需澄清当前仅 Agent 可用 |

---

## 4. 合理性评估总结

### 4.1 设计层面（合理）

1. **两个正交维度**（`plugin_type` 回答「做什么」、`source_type` 回答「怎么接」）切分清晰，并清理了与 `ai-providers` 语义重叠的历史取值 `provider`，方向正确。
2. **控制点位置正确**：把授权主控放在设计期、运行时只作纵深防御。文档（`plugin-types.md §7.1`）对早期「两头失控」的复盘准确，且已被代码实现吸收。
3. **fail-closed 贯彻一致**：写入校验整体拒绝（而非逐条跳过）、运行时跳过并告警（而非放行）、SSRF 解析失败即拒绝。
4. **安全细节到位**：SSRF 护栏覆盖 IPv4-mapped IPv6、CGNAT（`100.64.0.0/10`）、路径参数 URL 编码、不跟随重定向；`allow_destructive` 严格判 `is True`（字符串 `"true"` 不放行），避免配置误填静默绕过。
5. **两端口径共用常量**：`AGENT_EXPOSABLE_PLUGIN_STATUSES` / `DESTRUCTIVE_HTTP_METHODS` / `BINDABLE_SOURCE_TYPES` 在设计与运行时之间复用，从机制上抑制口径漂移。
6. **测试覆盖聚焦**：105 例后端 + 27 例前端，重点覆盖候选裁剪、端点解析不做隐式兜底、fail-closed 校验、SSRF 各网段、破坏性端点放行。

### 4.2 使用层面（需改进）

问题的共性可以归纳为一条：**插件模块自身的闭环已经做扎实，但「插件」与「Agent」两个模块之间尚未形成完整闭环。**

- 授权面只覆盖了 5 类工具中的 1 类（`plugin`），其余 4 类的 UI 入口缺失，且会在整表替换语义下被误删（§3.1）；
- 生命周期的两端未对齐：运行时加了 `source_type` 门禁的「半套」判据（§3.3）、删除时不评估影响面（§3.5）；
- 角色与导航未打通：管理侧与使用侧分属不同角色，界面上彼此不可见（§3.6、§3.7）。

### 4.3 建议的处理顺序

> **前置决策已闭合**：§7 提出的「插件定位是 HTTP 工具注册中心，还是多协议能力中心」**已定调为「多协议能力中心」**（理由见 [plugin-capability-model-design.md](plugin-capability-model-design.md) §2.5）。该二选一本身不成立——`source_type` 三值早已声明，HTTP-only 是落地进度而非定位选择；且平台唯一的外部能力注册面若限 HTTP，非 HTTP 能力只能走无治理的内联旁路。故下表第 8、9 项属**应当投入**，非可选。

| 优先级 | 项 | 理由 | 状态 |
|--------|-----|------|------|
| 1 | §3.1 非插件工具被清空 | 造成既有数据丢失，且用户无感知；后端加一个类型过滤即可根治 | **✅ 已实施**（M1-1） |
| 2 | §3.3 补 `source_type` 运行时门禁 | 一条常量即可闭合，消除「停用不生效」的语义矛盾 | **✅ 已实施**（M1-2） |
| 3 | §6.5 P1-C1 配置无法删除 + P1-C4 required 不生效 | 二者共同定义「写入契约」，一次改动可同时解决；不动则「配置已保存」始终是无含义状态 | **✅ 已实施**（M1-4） |
| 4 | §3.2 / §6.5 P1-C2 凭据加密 | 涉及安全基线，存在既有加密通道可复用；配置层与端点层需一并处理 | **✅ 已实施**（M1-3） |
| 5 | §6.5 P1-C3 测试按端点 id 选择 | 测试是配置流程唯一的验证环节，不可靠则前面全部白做 | ⬜ 待实施（P2） |
| 6 | §3.5 删除前展示影响面、§3.4 公共插件可管理 | 运维可控性 | ⬜ 待实施（P2） |
| 7 | §3.6 权限模型与文档对齐 | 需先确认产品意图（admin-only 还是权限细分） | ⬜ 待实施（P2） |
| 8 | §3.7 / §3.8 / §6.5 P2-C5～C10 | 体验与长期演进项 | ⬜ 待实施（P2） |
| 9 | §4.4 `plugin_type` 三值无行为差异 | 产品意图已定调：**该维度不成立，直接移除**（零行为差异 + 边界不可判定），保留 `source_type` 为唯一插件形态维度 | **✅ 已实施**（M2.0） |

> M1（优先级 1–4 及 P1-C11）已落地，详见 [§8](#8-m1--m20-实施记录已落地)。配置层单元测试缺口已补齐（`test_plugin_m1_fixes.py`）。P1-C11（端点 schema 接线）亦随 M1-5 完成。**优先级 9（§4.4 `plugin_type`）已随 M2.0 落地**，详见 [§8.6](#86-m20-实施记录已落地)。

### 4.4 关于「插件是否都是外部连接」：概念成立，但需两处限定

一个常见的概括是：**插件本质就是「外部工具 / 连接器 / 处理器」的注册**。这个概括在概念上成立——它曾恰好对应 `plugin_type` 枚举的三个取值（`tool` / `connector` / `processor`）。但落到当前实现，需要两处限定。**（M2.0 更新：`plugin_type` 已作为字段整体移除，见 [§8.6](#86-m20-实施记录已落地)；下文的「限定二」保留了移除前的诊断依据。）**

**限定一：`api_key` 非必需，`base_url` 才是硬依赖，且校验发生在调用时。**

| 配置项 | 是否必需 | 依据 |
|--------|---------|------|
| `base_url` | **必需**（或由 `api_spec.servers[0].url` 提供） | `plugin_executor.py:110-112` 二者皆缺则抛 `BadRequestException` |
| `api_key` | **可选** | `plugin_executor.py:48-52` 仅在配置了才注入 `Authorization: Bearer` |
| 端点 `headers` | 可选 | `plugin_executor.py:41-43` |

更值得注意的是：这个必需性**只在首次调用时校验**——创建插件、保存配置、`/test` 之外的路径都不校验 `base_url`。因此「必须先配 base_url」不是插件的准入条件，而是**调用时才暴露的运行时约束**（与 P1-C4「写入无校验」同源）。

**限定二（移除依据）：`plugin_type` 三个取值零行为差异，是纯分类标签——且边界不可判定，故 M2.0 已整体移除。**

全仓检索 `plugin_type` 的消费点仅三处：①列表过滤（`services/plugin.py:73-74`、`126-127`）②排序（`:132`）③工具目录回显（`api/agent.py:128`）。**不存在任何 `if plugin_type == ...` 的执行分支**，三者走完全相同的调用链路。

这意味着：`processor` 声明的「输入 → 输出纯处理」、`connector` 声明的「数据接入与回传」，在当前实现里都是**同一次 HTTP 调用**，没有独立的执行语义。把它理解为「工具/连接器/处理器」是**概念层面**的理解，实现层面三者尚未分化。

更关键的是：**即使要补齐差异化行为，也无法给出可判定的边界**——一个既读数据又返回结果的 HTTP 端点，同时满足 `tool` / `connector` / `processor` 三种描述；选择权完全落在填表人手里，而非落在系统可观测的属性上。因此当时 §4.3 第 9 项记录的「需先定产品意图」有两条出路：

1. 明确为「纯分类标签」并弱化 UI 暗示（原方案）；
2. **判定该维度本身不成立，整体移除，只保留真正决定调用分发的 `source_type`（已采纳，M2.0）。**

采纳方案 2 的理由是：一个既不驱动行为、又无法客观判定的字段，其唯一作用是让用户在创建时做一次无后果的选择，并为「选择即改变行为」制造错误的心理预期。移除后 `source_type`（`http` / `mcp` / `skill`）成为**唯一**插件形态维度，它是可判定的（决定走哪个执行器），也是运行时有真实判据的（`BINDABLE_SOURCE_TYPES` 门禁）。

**该概括唯一会被打破的维度始终是 `source_type`。** `source_type=http` 时"插件都是外部网络连接"成立；但 `mcp`（一个服务暴露多个工具）与 `skill`（**本地**技能包，无网络依赖）并非如此。当前 `BINDABLE_SOURCE_TYPES = {http}`（`plugin_policy.py`），后两者执行器未落地，故该概括在现状下成立，在未来不必然成立——这也是设计上预留的扩展点。

**结论**：这是「**外部 HTTP 服务的注册 + 凭据托管 + 端点级授权**」的一套通用外壳；`tool` / `connector` / `processor` 曾是贴在同一个外壳上的三个语义标签，M2.0 后已从数据模型、接口、前端与文档中全部剥离。能力形态的分化由 `source_type` 承担，而非由语义标签承担。

---

## 5. 验证记录

> **M2.0 后文件名变更**：`tests/test_plugin_types.py` → `tests/test_plugin_source_types.py`（`app/core/plugin_types.py` → `app/core/plugin_source_types.py`）。下段为 M1 时点的原始记录，命令中的旧文件名已不再存在；复跑请用 §8.4 中的当前路径。

```
# 后端（105 例通过，M1 时点）
cd backend && python -m pytest tests/test_plugin_types.py \
    tests/test_plugin_governance.py tests/test_agent_tool_catalog.py -q --basetemp=.pytest-tmp
# → 105 passed in 4.24s

# 前端（27 例通过，M1 时点；M2.0 后 pluginMeta 为 7 例）
cd frontend && npx vitest run src/pages/Agents/agentToolBinding.test.ts \
    src/pages/Plugins/pluginMeta.test.ts
# → Test Files 2 passed (2) / Tests 27 passed (27)
```

**覆盖盲区**：`grep -rn "update_config|get_config|add_endpoint|_sync_endpoints|import_endpoints" backend/tests/`
→ 无匹配。即**配置写入与端点管理这一层零单测覆盖**，本章 §6 的多数缺陷据此由静态走查得出。（该盲区已由 M1-4 的 `test_plugin_m1_fixes.py` 部分填补。）

---

## 6. 插件配置流程专项

§2.1 只把配置当作阶段 A 的一个步骤。本章单独展开「配置流程」——因为它是插件能否被真正调用的**前置条件**，也是当前问题最集中的一层。

### 6.1 配置的三个层次

插件配置分布在三张表、两个角色手上。这个分层是理解配置流程的关键：

| 层 | 载体 | 归属 | 谁配 | 影响范围 |
|----|------|------|------|---------|
| **L1 契约层** | `plugins.config_schema`、`plugins.api_spec` | 插件本身 | 插件作者（admin） | 所有租户 |
| **L2 端点层** | `plugin_endpoints`（endpoint / method / headers / request_body_schema / response_schema） | 插件本身 | 插件作者（admin） | 所有租户 |
| **L3 凭据层** | `plugin_configs`（name / value，按 tenant 隔离） | **租户** | 每个租户各自（admin） | 仅本租户 |

语义边界：**L1/L2 是"插件作者定义这个插件长什么样"，L3 是"这个租户用哪个地址和凭据接入它"**。公共插件（`tenant_id IS NULL`）之所以能被多租户复用，正是因为 L3 被独立出来。这个边界划分正确。

### 6.1.1 概念澄清：契约层 schema 与端点层 schema 不是同一件事

两层都叫 schema，容易被误读为重复定义。二者的区分标准是**填写者不同**：

| 维度 | 契约层 `plugins.config_schema` | 端点层 `plugin_endpoints.request_body_schema` |
|------|-------------------------------|---------------------------------------------|
| 回答的问题 | 租户**怎么连上**这个插件 | 模型**这次要传什么**参数 |
| 填写者 | 运维人员（人手填） | 模型（LLM 生成） |
| 归属粒度 | 插件级 × 租户级 | 端点级（method + path） |
| 典型内容 | `base_url` / `api_key` / 自定义 header | `{"query": "string", "top_k": "integer"}` |
| 落库位置 | `plugin_configs.value` | `plugin_endpoints.request_body_schema` |
| 运行时消费 | `_resolve_base_url` / `_merge_headers`（已消费） | **无消费者**（见 P1-C11） |

**不可合并的原因**：一个插件有 1 个连接、但有 N 个操作。`api_key` 对所有端点通用，故属插件级；而 `GET /v1/items` 与 `POST /v1/items/{id}` 的参数集合完全不同，只能属端点级。若把业务参数塞进 `config_schema`，就丧失表达"端点 A 要 a 参数、端点 B 要 b 参数"的能力。

**一句话自检**：`config_schema` 描述的是"你（租户）给我什么"，`request_body_schema` 描述的是"模型给我什么"。填写者不同，就不可能是同一个 schema。

> 当前端点的 `response_schema` 语义更弱：OpenAPI 导入时恒置 `None`（`services/plugin.py:260`），仅手工新增端点可填，运行时同样不读取——属纯文档字段。

### 6.2 配置流程步骤

```
C1  定义配置 Schema（可选）         plugins.config_schema（JSON Schema，文本粘贴）
      └─ 决定 L3 的 UI 形态：有 properties → 表单；否则 → 裸 JSON
C2  录入 OpenAPI 规范（可选）        plugins.api_spec
C3  生成 / 维护端点（L2）
      ├─ 创建插件时若带 api_spec → 自动解析 paths 建端点
      ├─ 已有插件 → 配置页「从 OpenAPI 导入」
      └─ 或手动「新增端点」逐条录入
C4  配置租户凭据（L3）               PUT /plugins/{id}/config
      ├─ schema 驱动：按 properties 渲染，逐字段读值
      └─ 裸 JSON：整对象编辑，键名约定 base_url / api_key / api_key_header / headers
C5  连通性测试                       POST /plugins/{id}/test
      ├─ 选端点 → 真实调用（非 GET 方法入参作请求体）
      └─ 不选端点 → 探测 base_url（GET /）
C6  保存生效                        下次 Agent 调用时读取
```

### 6.3 配置在执行期的消费链路

配置写入之后，`execute_plugin_call` 按固定优先级消费（`utils/plugin_executor.py`）：

| 配置项 | 来源与优先级 | 位置 |
|--------|-------------|------|
| `base_url` | 租户配置 `base_url` **>** `api_spec.servers[0].url` | `:23` |
| 请求头 | 端点 `headers` → 租户 `headers` 覆盖同名键 | `:36` |
| `api_key` | 租户 `api_key` → `Authorization: Bearer`（可用 `api_key_header` 改名）；已存在 authorization 头则跳过 | `:48` |
| 目标端点 | 工具配置 `endpoint_id` 优先，其次 `endpoint` 路径 | `plugin_policy.py:131` |
| 路径参数 | 从调用入参按 `{key}` 替换并 URL 编码 | `:56` |
| 其余入参 | `GET/DELETE/HEAD` → query；其余 → JSON body | `:125-128` |

> **未被消费的配置**：`endpoint.request_body_schema` 与 `response_schema` 在执行期**从不被读取**——目前是纯文档字段。这使端点层与契约层在功能上难以辨析，详见 §6.1.1 与 P1-C11。

### 6.4 配置流程的合理之处

1. **三层分离正确**：把"插件作者能力"与"租户接入凭据"解耦，是公共插件可复用的前提；`plugin_configs` 上的 `uq_plugin_config (plugin_id, tenant_id, name)` 唯一约束保证了租户间不串扰。
2. **两条 UI 路径覆盖面完整**：schema 驱动适配"插件作者规范交付"的情形，裸 JSON 适配"临时插件、没有 schema"的情形；裸 JSON 分支还给出了键名约定（`base_url` / `api_key` / `api_key_header` / `headers`）与 base_url 缺失告警（`PluginConfig.tsx:572-589`），引导质量较高。
3. **敏感字段在展示层被识别**：`/key|secret|token|password/i` 命中即用 Password 控件（`PluginConfig.tsx:155`），避免肩窥式泄露。
4. **配置不能绕过护栏**：无论 `base_url` 配成什么，最终 URL 都要过 `assert_outbound_url_allowed`；`follow_redirects=False` 使重定向无法改道；路径参数编码使 `../`、`//host` 无法越界。降级开关 `PLUGIN_BLOCK_PRIVATE_NETWORK` 语义明确（有意识的降级 + 需网络层配合）。
5. **`get_config` 只查本租户**（`services/plugin.py:345-356`），与 L3 的隔离语义一致。

### 6.5 配置专项问题清单

#### P1-C1 配置项只能新增/覆盖，无法删除

| 证据 | 内容 |
|------|------|
| `schemas/plugin.py:137` | `PluginConfigUpdateRequest` 只有 `items`，无删除语义 |
| `services/plugin.py:358-382` | `update_config` 逐条 upsert，**无删除分支** |
| `services/plugin.py:345-356` | `get_config` 返回本租户该插件下的**全部**行 |

**现象**：用户在裸 JSON 里删掉 `api_key` 键再保存 → 返回"配置已保存" → 重新进入配置页，`api_key` 依然在。

**影响**：`保存` 不等于 `配置就是这个样`。误配的凭据无法撤销；凭据泄露后只能"改值"不能"移除"；schema 与裸 JSON 两种模式切换时会留下僵尸配置项（例如 schema 未声明 `base_url` 时，之前存的 `base_url` 仍在库中且仍在生效，但界面上不可见）。

**建议**：把 `update_config` 定义为**全量替换**语义——保存时删除本租户该插件下不在 `items` 中的行（同一事务内），或在请求体中显式增加 `removed: [name]`。前者更符合用户对"保存"的直觉。

---

#### P1-C2 凭据明文存储与明文回显（配置视角补充）

§3.2 已述，配置视角需补充两点：

- 明文落点不止 `plugin_configs.value`，**`plugin_endpoints.headers` 同为 JSON 明文**（端点层也可能带 `X-Api-Key`）；
- 前端用 `Password` 控件遮挡的只是渲染层，`GET /plugins/{id}/config` 的响应体中 `value` 仍为明文原值。

**建议**：统一收敛到 `app/utils/encryption.py` 的 Fernet 通道，敏感键加密存储 + 读取掩码 + 空值不覆盖（方案见 §3.2）。

---

#### P1-C3 测试弹窗按"路径"选择端点，同路径多方法会选错

| 证据 | 内容 |
|------|------|
| `PluginConfig.tsx:712` | `options={endpoints.map((e) => ({ value: e.endpoint, label: `${e.method} ${e.endpoint}` }))}` —— `value` 用路径 |
| `services/plugin.py:392-399` | 按 `PluginEndpoint.endpoint == request.endpoint` + `.first()` 取端点 |

**现象**：OpenAPI 中 `GET /v1/items` 与 `POST /v1/items` 是常态；两者在下拉框里 `value` 相同，选中任一项的行为一致；后端 `.first()` 的选取依赖 `created_at` 顺序，而 `created_at` 精度可能相同 → 顺序不稳定。

**影响**：用户"选中的端点"与"实际调用的端点"可能不一致，测试结果不可信——这恰好破坏了配置流程中最关键的验证环节。

**建议**：`value` 改用 `endpoint.id`，请求体改传 `endpoint_id`（后端保留 `endpoint` 路径兼容历史调用）。

---

#### P1-C4 `config_schema` 的 required 不生效，且后端从不校验

| 证据 | 内容 |
|------|------|
| `PluginConfig.tsx:174-184` | `renderSchemaField` 的 `Form.Item` **未设置 `rules`** |
| `models/plugin.py:76` | 注释自认"由前端/调用方保证" |
| 全仓检索 | `config_schema` 仅出现在 schema 定义、模型、创建赋值处，**无任何校验逻辑** |

**影响**：插件作者在 schema 中声明的 `required: ["base_url"]` 形同虚设；用户可在缺 `base_url` 的情况下看到"配置已保存"，直到 Agent 调用或测试时才失败。且 schema 驱动分支**没有**裸 JSON 分支那条 base_url 缺失告警——配了 schema 的插件，配置体验反而更弱。

**建议**：前端按 `schema.required` 生成 `Form.Item rules`；后端在 `update_config` 中按 `config_schema` 做一次 JSON Schema 校验（fail-closed），让"配置已保存"成为有含义的状态。

---

#### P2-C5 编辑插件时替换 api_spec 不会同步端点，UI 文案与实际不符

| 证据 | 内容 |
|------|------|
| `services/plugin.py:183-184` | `create` 中 `if data.api_spec: self._sync_endpoints_from_spec(plugin)` |
| `services/plugin.py:187-203` | `update` **没有**该调用 |
| `PluginList.tsx:383` | 编辑弹窗 `api_spec` 字段 extra 文案："提供后将自动解析生成插件端点" |

**影响**：编辑时替换规范后端点不更新，而界面文案暗示已同步；用户必须自行到配置页点「从 OpenAPI 导入」且无提示。

**建议**：`update` 中检测 `api_spec` 变化时同步调用 `_sync_endpoints_from_spec`，或修正文案并给出显式的"重新导入"引导。

---

#### P2-C6 「导入端点」是 append-only，不反映规范的新变化

`_sync_endpoints_from_spec`（`services/plugin.py:221-267`）只按 `(method, path)` 内存去重后**新增**：不更新已存在端点的 `description` / `request_body_schema`，也不移除规范中已删除的端点。

**影响**：规范迭代后端点列表同时残留旧端点与旧描述；候选目录的 200 条上限可能被无用的历史端点占用。

**建议**：改为「按规范对齐」语义（新增 + 更新 + 标记失效），或至少在导入返回中区分"新增 / 已存在 / 未在规范中"三类计数，让用户知道差异。

---

#### P2-C7 端点无唯一约束，可产生重复项

`plugin_endpoints` 无 `(plugin_id, method, endpoint)` 唯一约束（`models/plugin.py:86-111`、`phase7_plugin_system.py:59-72`），手动新增可重复入库。

**影响**：候选目录出现重复端点；`selectionsToToolPayload` 对同名工具会**静默保留先出现者、丢弃后者**（`agentToolBinding.ts:115`）→ 用户勾选两个却只生效一个，且无提示。

**建议**：补唯一约束 + 迁移；前端新增端点时做重复检测并提示。

---

#### P2-C8 列表页「测试」必然走连通性探测，失败无详情

`PluginList.tsx:179-190` 的测试按钮不传 `endpoint`，因此**必然**执行 base_url 探测；若租户未配 `base_url` 且 spec 无 `servers`，直接抛 `ValidationException`（`services/plugin.py:420`）。此时 Drawer 不打开（`:417` 以 `testResult !== null` 为条件），用户只看到一句 toast。（配置页的测试弹窗因错误块以同一个 `testResult` 为条件，反而能正常展示失败信息。）

**建议**：列表页测试按钮改为跳转配置页测试，或在未配 base_url 时直接给出可操作提示。**同类问题**：`PluginList.tsx:69` 硬编码 `page_size: 200` 且无分页信号，后端已支持的 `plugin_type`/`source_type`/`status` 三个过滤参数在 UI 中完全未暴露。

---

#### P2-C9 配置变更无审计、无版本

`plugin_configs` 只有 `created_at` / `updated_at`，`update_config` 为覆盖式写入；审计中间件只记录 API 层写操作（`middleware/audit.py:14`），因此"改了配置"只能记为一次 `PUT /plugins/{id}/config`，**记不到改了什么**。凭据轮换不可追溯。

**建议**：审计日志中记录变更的**键名**（不记录值），使凭据轮换有据可查。

---

#### P2-C10 端点级 headers 可被租户配置覆盖

`_merge_headers`（`utils/plugin_executor.py:36-53`）先放端点头、再用租户 `headers` 覆盖同名键。

**影响**：语义上是"租户可覆盖"，对多租户 SaaS 场景属合理弹性；但端点作者若想表达"该头不可被改写"，当前无机制。

**建议**：如需收紧，可约定端点 `headers` 优先、租户只能补充未声明的头名。

---

#### P1-C11 端点层 schema 声明了但未接线，模型无参数契约

> 说明：问题编号在文档内保持稳定，不因插入而重排，故本项编号接续在 P2-C10 之后。

**现状（三处证据）**：

| 环节 | 事实 | 位置 |
|------|------|------|
| 写入侧 | OpenAPI 导入只抽 `requestBody.schema`，`response_schema` 恒为 `None` | `services/plugin.py:245-262` |
| 消费侧 | 运行时工具为 `Tool(name, description, func=plugin_func)`，签名仅 `query: str`；schema **未注入**工具描述或参数定义 | `services/agent.py:567-607` |
| 执行器 | `execute_plugin_call` 的参数列表中没有 `request_body_schema` | `utils/plugin_executor.py:77-87` |

**运行时实际行为**：模型只能看到不透明的 `query` 字符串，参数名无从得知。若输出恰好是 `{` 开头的 JSON 字符串 → `json.loads` 成 params；否则 → 包成 `{"query": query}`（`agent.py:577-584`）。字段名猜错时由远端返回报错，本地无任何预校验。

**影响**：端点层 schema 具备"工具契约"的数据形态，却未承担契约职责。这是 §6.1.1 中两层 schema 显得重复的直接原因，也使"插件只是 HTTP 代理"和"插件可作为 LLM 工具"之间缺少分界——当前实质上更接近前者。

**建议**：把 `request_body_schema` 接入工具构建链路，二选一：
1. 生成结构化 `args_schema`（LangChain `StructuredTool` / Pydantic 模型），让模型按字段填参；
2. 最低成本方案——将 schema 序列化后拼入 `description`，使模型可读参数名与类型。

无论采用哪种，均应同步补齐 `/test` 与运行时的字段名一致性校验，让"参数不对"在本地失败而非远端返回 4xx。

---

### 6.6 配置流程的合理性小结

**分层设计合理，执行期消费链路清晰无歧义。** `base_url` 租户优先、`headers` 租户覆盖、`api_key` 自动 Bearer、端点必须显式指定——每条规则都能在代码中找到唯一落点。

**问题集中在"写入"这一侧**，可归纳为同一句话：**配置层缺少一个明确的「写入契约」。**

| 缺陷 | 后果 |
|------|------|
| 写入只能 upsert，无法表达"删除"（P1-C1） | 「保存」≠「配置就是这个样」 |
| 写入无校验，required 不生效（P1-C4） | 「配置已保存」不蕴含「配置可用」 |
| 敏感值无保护（P1-C2） | 配置层成为凭据的明文落点 |
| 读取侧按路径取端点（P1-C3） | 唯一可依赖的验证环节不可靠 |
| 端点 schema 未接线（P1-C11） | 端点层与契约层辨析不清，模型无参数契约 |

一个完整的写入契约应回答三个问题：**一次提交是全量还是增量**（P1-C1）、**提交后必须满足哪些不变量**（P1-C4）、**敏感值如何存取**（P1-C2）。建议以 `update_config` 为切入点先固化这个契约，再向外扩到 P1-C3 与 P2-C5～C10 的体验项。

> **测试覆盖提示**：后端 `tests/` 中对 `update_config` / `get_config` / `add_endpoint` / `_sync_endpoints_from_spec` **无任何用例**（检索结果为空）。现有 105 例覆盖的是策略与目录裁剪，配置写入语义完全裸奔——这也是上述缺陷能长期存留的原因之一。修复 C1–C4 时应同步补齐配置层的单元测试。

---

## 7. 能力模型的覆盖面诊断与改造建议（待评审）

> 本章由一次针对「本地 MCP 搜索插件如何配置」的追问引出。结论是：**当前模型只能表达 HTTP 接入，即便二期补上 MCP 客户端也无法录入本地 MCP 服务**——限制不在执行器，而在数据模型的字段形态。

### 7.1 问题的提出

典型反例：一个搜索插件是**本地 MCP 服务**（stdio 传输，随客户端进程启动）。它具备三个特征：

- 没有 HTTP 端点 → `base_url` 无意义，无从填写；
- 没有路径与 HTTP 动词 → `endpoint` / `method` 无从填写；
- 能力清单在服务启动后由 `tools/list` **动态返回** → 无法静态录入端点。

按当前模型，运维在配置页既没有可填的 `base_url`，也无法新增端点，插件因此既无法保存完整配置，也不能被授权给 Agent。

### 7.2 现状核对：链路上只有一层是形态无关的

逐字段核对本地 MCP 场景的可表达性：

| 环节 | 现状 | 本地 MCP 场景 | 可否表达 |
|------|------|--------------|---------|
| `plugins.api_spec` | OpenAPI 文档 | 无（MCP 无 OpenAPI） | 否 |
| `plugin_endpoints.endpoint` | `String(500) NOT NULL`，路径 | 无路径 | 否 |
| `plugin_endpoints.method` | `String(10) NOT NULL`，HTTP 动词 | 无动词 | 否 |
| `check_plugin_bindable` | 要求 `endpoint_count >= 1` | 能力需运行时发现，静态为 0 | 否 |
| `_resolve_base_url` | 需 `base_url` 或 `api_spec.servers` | 无地址 | 否 |
| `execute_plugin_call` | `httpx` 同步请求 | 需 MCP 客户端 + stdio 管道 | 否 |
| `BINDABLE_SOURCE_TYPES` | `frozenset({"http"})` | `mcp` 不在其中 | 否 |
| `requirements.txt` | 无 MCP SDK 依赖 | — | 否 |
| `plugin_configs.value` | 任意 JSON | 可容纳 `command` / `args` / `env` | **是** |
| `plugins.config_schema` | 任意 JSON Schema | 可描述 command/args/env | **是** |

**结论**：整条链路只有**凭据层**是形态无关的（因为它只是 JSON 存储 + JSON Schema 驱动），**端点层与执行器都是 HTTP 专有的**。这正是「适用场景太小」的根因——问题不在"缺少执行器"，而在"数据结构里没有第二种接入方式的容身之处"。

### 7.3 根因：把某一种协议的形态当成了插件的形态

L2 端点层的字段（`endpoint` 路径 / `method` 动词 / `request_body_schema`）实际描述的是**「HTTP 协议下的调用描述」**，却被建模为插件的固有结构。MCP 场景需要的是另一组完全不同的字段：

```json
{ "command": "npx", "args": ["-y", "@xxx/search-mcp"], "env": { "SEARCH_API_KEY": "sk-..." } }
```

这正是 MCP 生态的标准接入写法（Claude Desktop / Cursor 等均采用此形态）。

一个关键区分：**租户级配置的需求依然存在**——本地搜索服务往往仍需一个 API key，只是通过 `env` 传递而非 `Authorization` 头。所以「凭据层」这个概念是正确且通用的；**不通用的只有 `base_url` 这个字段名及其 HTTP 语义**。

同理，`plugin_type` 的三值也是从「外部 HTTP 服务」视角划分的：一个纯本地处理器（如文本切分）既不需要 `base_url`，也不需要网络——`docs/plugin-types.md` §2.2 把"需要 `base_url` / `api_key`"写进 `connector` 的定义，即已隐含了 HTTP 前提。

### 7.4 改造建议：把两个概念各自多态化

社区通行做法（Dify / Coze / n8n 等平台）是把「能力单元」与「接入描述」分离，并各自按协议多态。

**概念一 · 能力单元（CapabilitySpec）**——可调用的一项能力，描述字段随 `source_type` 变化：

| `source_type` | 能力描述字段 | 来源 |
|---------------|-------------|------|
| `http` | `path` / `method` / `request_schema` / `response_schema` | OpenAPI 解析或手工录入 |
| `mcp` | `tool_name` / `input_schema` | 运行时 `tools/list` **动态发现** |
| `skill` | `doc_path` / `entry` | 技能包清单 |

**概念二 · 接入描述（ConnectionSpec）**——租户如何连上它，同样随 `source_type` 多态：

| `source_type` | 租户需配置的字段 |
|---------------|-----------------|
| `http` | `base_url` / `api_key` / `headers` |
| `mcp`（stdio） | `command` / `args` / `env` |
| `mcp`（sse / streamable-http） | `url` / `headers` |
| `skill` | `skill_dir` / 环境变量 |

两种常见实现落法：

- **单表 + 判别字段**：`plugin_capabilities(source_type, spec JSON)`，`spec` 的 schema 随 `source_type` 校验——迁移成本低、扩展快；
- **分表**：`plugin_http_endpoints` / `plugin_mcp_tools` 各自字段明确——类型安全更强。

建议过渡路径：先引入判别字段与 JSON `spec`，保留 `plugin_endpoints` 作为 `http` 分支，待 MCP 落地后再评估是否分表。

### 7.5 对既有设计的三处冲击

引入第二种接入方式，会连带影响三处既有设计：

1. **`check_plugin_bindable` 的「至少 1 个端点」判据不再普遍成立**。MCP 能力在运行时才发现，静态端点数为 0，该判据会把合法插件排除在候选目录之外。判据需按 `source_type` 分化。
2. **候选目录（`tool-catalog`）从「静态查询」变为「探测 + 缓存」**。当前目录是纯数据库查询；MCP 场景需连接服务、拉取 `tools/list`、缓存并处理不可用降级——这会引入延迟与新的失败路径，属产品交互层面的新问题。
3. **SSRF 护栏不完全适用**。`net_guard` 面向出站 HTTP；stdio MCP 的等价风险是**本地进程执行**——`command` / `args` 由租户可控即等于任意命令执行能力。该风险高于 SSRF，需要独立的白名单与沙箱策略，**不能复用现有护栏**。

### 7.6 分阶段建议

| 阶段 | 内容 | 说明 |
|------|------|------|
| 1 | ~~明确产品定位：「HTTP 工具注册中心」还是「多协议能力中心」~~ → **已定调：多协议能力中心** | 见 [design §2.5](plugin-capability-model-design.md)。结论是该二选一不成立：`source_type` 三值早已声明，HTTP-only 是落地进度；且限 HTTP 会使非 HTTP 能力只能走无治理的内联旁路（`function` / `api` 逐 Agent 内联） |
| 2 | 若定位为多协议：先固化 `source_type` 维度的字段契约（CapabilitySpec / ConnectionSpec 的 schema） | 只改模型与校验、不接执行器，可先让配置"录得进去" |
| 3 | 落地 MCP 客户端（stdio 与 sse / streamable-http）、工具动态发现与缓存 | 须同步补齐本地进程执行的沙箱与命令白名单 |
| 4 | `skill` 加载与沙箱执行 | 与 MCP 共享「本地执行」的安全基础设施 |

### 7.7 待确认事项

> 按项目约定，本章为**方案建议，暂不实施**。进入实施前需先确认以下事项：
>
> 1. ~~插件的产品定位是「HTTP 工具注册中心」还是「多协议能力中心」？~~ → **已定调：多协议能力中心**，理由见 [design §2.5](plugin-capability-model-design.md)。剩余为执行层面选择。
> 2. MCP 需支持哪些传输形态（stdio / sse / streamable-http）？
> 3. 本地进程执行的安全边界如何界定（命令白名单？容器隔离？）——这是引入 MCP 后风险最高的部分，**须先于 M2 主体落地**。
> 4. 数据模型选 A / B / C（推荐 B）。
> 5. `plugin_type` 三分法去留（保留并兑现 / 降级为纯标签 / 移除）。
>
> 确认后再进入实施；实施时会同步补齐 §6.6 指出的配置层单测缺口。

> **本章的完整方案已单独成篇**：见 [plugin-capability-model-design.md](plugin-capability-model-design.md)。
> 该文档以 MCP 规范、Dify `ToolProviderType`、Anthropic 工具设计准则三个成熟参照系为基准，给出目标模型的五层职责划分、三种数据模型方案的取舍对比、按来源分化的安全模型、M1–M3 实施路线与验收标准，并将本章的 3 个待确认事项扩展为 6 项待决策清单。

---

## 8. M1 / M2.0 实施记录（已落地）

> M1 是 [design §路线图](../docs/plugin-capability-model-design.md) 中**不依赖大数据模型改造**即可落地的修复集合：沿用现有「插件 = HTTP 能力」模型，仅把已发现的五处行为缺陷与一处安全缺口补上。M2（多协议能力中心数据模型）、M3（命名空间 / 按需加载 / 审计配额）仍按计划待评审后实施。

### 8.1 改动清单

| 编号 | 问题（对应 §/review） | 文件 · 函数 | 改动要点 |
|------|----------------------|-------------|----------|
| M1-1 | 更新 Agent 误删非插件工具（§3.1） | `repositories/agent.py` · `AgentToolRepository.delete_by_agent`；`services/agent.py` · `update_agent` | 新增 `tool_type` 参数，更新时仅重建 `plugin` 类工具；`knowledge`/`api`/`function`/`workflow` 由各自流程管理，本端点不触碰 |
| M1-2 | 运行时缺 `source_type` 判据（§3.3） | `core/plugin_policy.py` · `check_plugin_source_gate`；`services/agent.py` · `_build_langchain_tools` | 新增运行时门禁 0：插件被改为未实现的接入方式（mcp/skill）后，原有 http 绑定立即失能；与 `check_plugin_bindable` 共用 `BINDABLE_SOURCE_TYPES`，避免 fail-open |
| M1-3 | 凭据明文落库（§3.2） | `models/plugin.py` · `PluginConfig.value_encrypted`；`utils/encryption`；`services/plugin.py` · `_load_config_dict`/`get_config`/`_upsert_config_row`；`schemas/plugin.py` · `PluginConfigItem.has_value`；`frontend/.../PluginConfig.tsx` + `types/plugin.ts` | 真实凭据以 Fernet 密文落库；`value` 列退化为脱敏回显；敏感项回显契约改为 `value=None + has_value=True`（详见 8.3） |
| M1-4 | `update_config` 写入契约缺失删除与必填校验（P1-C1 / P1-C4） | `schemas/plugin.py` · `PluginConfigUpdateRequest.remove`；`services/plugin.py` · `update_config`/`_validate_required` | 支持按 name 显式删除；提交前校验 `config_schema.required`（fail-closed，早于任何写入）；`value=None` 语义为「未改动、保留既有」 |
| M1-5 | 端点入参 schema 未接入工具参数（P1-C11） | `services/agent.py` · `_build_args_schema` + `_build_langchain_tools` | 端点声明 `request_body_schema` 时，构造 Pydantic `args_schema` 注入 LangChain Tool，并在描述中提示参数；否则退化单字符串 `query` |

### 8.2 数据库迁移

`backend/alembic/versions/g1h2i3j4k5l6_encrypt_plugin_config_values.py`

- 为 `plugin_configs` 增加 `value_encrypted`（Text，可空）列。
- 回填历史明文行：加密真实值 + 脱敏 `value`；依赖 `FERNET_KEY`，单行失败不影响整体迁移（legacy 回退逻辑兜底）。
- `down_revision = "c8d9e0f1a2b3"`（当前合并头）；已确认 `alembic heads` 单一，且 `alembic upgrade head` 已在实库执行、`information_schema` 已验证列存在。

### 8.3 敏感项回显契约（关键决策）

**不用 `"********"` 占位回显，改用 `value=None + has_value=True`**，与 `AIProvider.has_api_key` 对齐。原因：

- 若回显 `"********"`，前端表单会把占位当真实值回填，保存时以占位覆盖真实凭据 → 凭据被静默清空（regression）。
- 采用 `value=None + has_value=True` 后，前端保存时跳过「空值且原本已设置」的敏感字段（见 `PluginConfig.tsx` 的 `isSecretName` + `hasValueRef` 逻辑与裸 JSON 模式下的占位过滤），既避免泄露也避免误覆盖。

### 8.4 测试覆盖

| 套件 | 范围 | 结果 |
|------|------|------|
| `tests/test_plugin_m1_fixes.py`（新增，121 例） | M1-1/2/3/4/5 全链路：门禁拒绝、Agent 更新保留非插件工具、`value_encrypted` 落库 + 解密、`has_value` 回显、删除、必填校验、`null` 保留既有、args_schema 注入 / `query` 退化 | 全部通过 |
| `tests/test_plugin_governance.py`（对齐 2 处 fake 加 `source_type="http"`） | 设计期/运行时门禁、SSRF 护栏 | 通过 |
| 后端全量 | 含 M1 改动 | 362 通过（3 例 `test_reranker` 为 `sentence_transformers` 未装之既有无关失败） |
| 前端 | `tsc --noEmit` + `pluginMeta`(8) / `agentToolBinding`(19) | 类型检查 0 错误，27 例通过 |

集成测试使用内存 SQLite（`Base.metadata.create_all`）+ `monkeypatch` 注入 `FERNET_KEY`，与 `test_encryption.py` 一致，无需真实数据库。

### 8.5 验证命令（复跑）

```bash
# 后端 M1 针对性用例
cd backend && .venv/bin/python -m pytest tests/test_plugin_m1_fixes.py tests/test_plugin_governance.py -q

# 迁移一致性
.venv/bin/python -m alembic heads        # M1 时点为 g1h2i3j4k5l6；M2.0 后为 h2i3j4k5l6m7
.venv/bin/python -m alembic upgrade head

# 前端
cd frontend && npm run lint && npm run test -- pluginMeta agentToolBinding
```

---

### 8.6 M2.0 实施记录（已落地）

> **M2.0 是 M2 的零依赖前置**：不引入新的数据模型与执行器，只做一次**语义收敛**——把零行为差异、边界不可判定的 `plugin_type`（能力形态：tool / connector / processor）从全链路移除，保留 `source_type`（接入方式：http / mcp / skill）为**唯一**插件形态维度。它是 §4.3 第 9 项（§4.4）的落地，也是 M2.1（多协议数据模型）不再背负数形维度的前提。

**决策依据**：见 §4.4「限定二」。核心两条：① `plugin_type` 零执行分支，三值走同一条调用链路；② 一个既读又写的 HTTP 端点同时满足三种描述，**边界不可判定**，故不能靠补差异化行为来救活该维度。方案对比见 [plugin-m2-m3-implementation-plan.md](plugin-m2-m3-implementation-plan.md) 决策 4。

#### 8.6.1 改动清单

| 层 | 文件 | 改动要点 |
|----|------|----------|
| 类型体系 | `core/plugin_types.py` → **`core/plugin_source_types.py`** | 模块重命名；删除 `PluginType` / `PLUGIN_TYPE_META` / 默认值；docstring 记录移除理由。`PluginSourceType` 成为唯一定义处 |
| 数据模型 | `models/plugin.py` | 删除 `plugin_type` ORM 列 |
| 接口契约 | `schemas/plugin.py` | 删除 `DEFAULT_PLUGIN_TYPE` / `PluginType` 导入；`PluginCreate` / `PluginUpdate` / `PluginOut` 移除 `plugin_type` |
| 服务层 | `services/plugin.py` | `list()` 与 `list_bindable_for_agent()` 移除 `plugin_type` 过滤与 `order_by`；`create()` 不再写入该字段 |
| 路由 | `api/plugin.py`、`api/agent.py` | 移除 `list_plugins` / `get_agent_tool_catalog` 的 `plugin_type` Query 参数与工具目录回显字段 |
| 暴露策略 | `core/plugin_policy.py` | 导入路径改为 `plugin_source_types`（判据逻辑本身不变） |
| 迁移 | `alembic/versions/h2i3j4k5l6m7_drop_plugin_type.py` | `DROP COLUMN plugins.plugin_type`，带 `inspect().get_columns()` 幂等守卫（MySQL 非事务 DDL） |
| 前端类型 | `types/plugin.ts`、`types/agent.ts` | 移除 `PluginType` 类型与 `Plugin` / `PluginCreateRequest` / `PluginUpdateRequest` / `ToolCatalogPlugin` 中的同名字段 |
| 前端 API | `api/plugin.ts`、`api/agent.ts` | 移除 `listPlugins` / `getToolCatalog` 的 `plugin_type` 参数 |
| 前端页面 | `pages/Plugins/PluginList.tsx`、`PluginConfig.tsx`、`pages/Agents/AgentForm.tsx` | 移除表单默认值 / 提交载荷 / 「类型」表格列 / 「能力形态」Form.Item / Descriptions.Item / Tag 渲染（共 13 处） |
| 前端元数据 | `pages/Plugins/pluginMeta.ts` | 删除 `PLUGIN_TYPE_META` / `PLUGIN_TYPE_OPTIONS` / `pluginTypeMeta`，仅保留 source 系列 |
| 测试 | `tests/test_plugin_source_types.py`（新）、`tests/test_plugin_types.py`（删）；前端 `pluginMeta.test.ts`（重写）、`agentToolBinding.test.ts`（2 处 fixture） | 除正向覆盖外，新增**移除守卫**：模块不可导入、ORM 无该列、Schema 无该字段、`PluginCreate(plugin_type=...)` 被忽略 |

#### 8.6.2 数据库迁移

`backend/alembic/versions/h2i3j4k5l6m7_drop_plugin_type.py`（`down_revision = "g1h2i3j4k5l6"`）

- `upgrade()`：先 `inspect()` 判列存在再 `DROP COLUMN`，避免重复执行报 1091；`downgrade()` 反向补列并带 `server_default="tool"`。
- **已在实库执行**（非仅交付文件）：由 `ai-studio-backend` 容器入口的 `alembic upgrade head` 落库，日志 `Running upgrade g1h2i3j4k5l6 -> h2i3j4k5l6m7`。
- 直连库验证：`information_schema.columns` 中 `plugins` 已无 `plugin_type`（显式 COUNT = 0）；`alembic_version` = `h2i3j4k5l6m7`。

#### 8.6.3 测试覆盖

| 套件 | 范围 | 结果 |
|------|------|------|
| `tests/test_plugin_source_types.py`（新增，13 例） | source 值集合、Schema 校验、meta 完备性 + 4 条移除守卫 | 通过 |
| `tests/test_plugin_m1_fixes.py`（16 例）+ `test_plugin_governance.py`（61 例）+ `test_agent_tool_catalog.py`（32 例） | M1 全链路在移除后仍成立 | 122 通过 |
| 后端全量（容器内，`--ignore=tests/test_celery_config.py`） | 全仓回归 | **382 通过 / 7 失败**（3 例 `test_reranker` 缺 `sentence_transformers`；4 例 `test_knowledge_vector_delete` 环境态，单独跑必过，零插件引用）——均为既有环境性失败 |
| 前端 | `tsc --noEmit` + `pluginMeta`(7) / `agentToolBinding`(19) | 类型检查 0 错误，26 例通过 |

#### 8.6.4 端到端冒烟

在容器内用 `JWT_SECRET_KEY` 自签 token，实测两个曾被改动的端点：

| 端点 | 结果 |
|------|------|
| `GET /plugins` | 200，响应含 `source_type`、**不含 `plugin_type`** |
| `GET /agent/agents/tool-catalog` | 200，回显结构正常 |

后端日志无异常。

#### 8.6.5 残留检查

`grep -rn "plugin_type"` 全仓仅剩三类命中，均属允许范围：

1. 历史迁移（`phase7_plugin_system.py`、`a7b8c9d0e1f2`）——**不可改**，迁移是历史快照；
2. M2.0 移除守卫测试与 `plugin_source_types.py` 的说明性 docstring；
3. 新迁移 `h2i3j4k5l6m7` 自身（`DROP COLUMN` 的对象名）。

即满足验收标准「全仓无功能性残留（文档与迁移除外）」。

#### 8.6.6 验证命令（复跑）

```bash
# 后端 M2.0 针对性用例
cd backend && .venv/bin/python -m pytest tests/test_plugin_source_types.py \
    tests/test_plugin_m1_fixes.py tests/test_plugin_governance.py \
    tests/test_agent_tool_catalog.py -q --basetemp=.pytest-tmp

# 迁移一致性（应仅 h2i3j4k5l6m7）
.venv/bin/python -m alembic heads

# 前端
cd frontend && npx tsc --noEmit && npx vitest run \
    src/pages/Plugins/pluginMeta.test.ts src/pages/Agents/agentToolBinding.test.ts
```

---

## 8.7 带工具对话链路的缺陷修复（2026-09-15，已落地）

### 8.7.1 现象与复现

给 Agent 绑定示例插件后发起对话，前端在**会话最上方**弹出：

```
模型调用失败  Prompt missing required variables: {'tool_names'}
```

### 8.7.2 根因：四个缺陷叠加，链路从未真正跑通

修复过程中逐层实测，发现这不是「一个」bug——**任何一个单独修掉都仍然不可用**。

| # | 缺陷 | 位置 | 实测证据 |
|---|------|------|----------|
| 1 | 文本 ReAct 提示词缺 `{tool_names}`，`create_react_agent` 在**装配阶段**即抛 `ValueError` | `agent.py` 旧 `chat`/`chat_stream` 内联模板 | `create_react_agent(...)` → `ValueError: Prompt missing required variables: {'tool_names'}`；它强制校验 `tools`/`tool_names`/`agent_scratchpad` 三者齐备 |
| 2 | 工具用**单入参** `Tool` 构建，任何输入都被折叠成一个**位置参数** | `_build_langchain_tools`（5 处 `Tool(...)`） | `tool.run('AI-Studio')` → 字符串塞进第一个形参（闭包用 `_plugin`）→ `'str' object has no attribute 'name'`，插件**静默不执行** |
| 3 | 端点入参 `args_schema` 有多字段，与单入参 `Tool` 语义冲突 | 同上 | `tool.invoke({'q':..., 'sort':...})` → `ToolException: Too many arguments to single-input tool` |
| 4 | 流式用 `AgentExecutor.astream`，它只产出**聚合**事件 | 旧 `chat_stream` | 实测仅 3 条 `AddableDict`（keys=`actions`/`steps`/`output`），**没有** `.content`，逐字流式无从取数 |

叠加结论：**「Agent 绑定工具」这条路径此前不可能成功**——缺陷 1 让它直接崩，缺陷 2 让工具即使被调用也不执行。之所以此前未暴露，是因为**没有任何 Agent 绑定过工具**（本项目的 Agent 均为无工具状态）。示例插件是第一个绑定工具的场景，于是四条缺陷同时亮相。

### 8.7.3 修复方案：改走原生工具调用（function calling）

放弃文本 ReAct，改用 `create_tool_calling_agent` + `StructuredTool` + `astream_events(v2)`：

| 决策 | 理由 |
|------|------|
| 文本 ReAct → **原生工具调用** | 前者要求模型把入参写成 `Action Input:` 裸文本，与已落地的**结构化参数**（review P1-C11）天然冲突；后者把 JSON Schema 交给模型、以 `dict` 收回，二者才是配套的。实测 `deepseek-v4-flash` 原生返回 `tool_calls`，参数完整正确 |
| `Tool` → **`StructuredTool`**（全部 5 个分支） | `Tool` 是单入参工具，多字段 schema 必然抛 `Too many arguments`；单字符串工具（knowledge/api/function/workflow）也显式声明 `_QUERY_ARGS = {query: str}`，让模型知道内容该放哪个键，而不是一个语义不明的裸字符串 |
| `AgentExecutor.astream` → **`astream_events(v2)`** | 只有订阅底层 `on_chat_model_stream` 才有逐字内容。实测 606–840 个内容块/轮 |
| 新增 `AgentAssemblyError` | 装配失败（提示词/工具/模型不支持 function calling）**根本没走到模型**，不能再报成「模型调用失败」误导用户去查 API Key |

### 8.7.4 顺带修复的既有缺陷

| 缺陷 | 说明 |
|------|------|
| 带工具路径**丢失 system_prompt 与对话历史** | 旧实现只传 `{"input": message}`，Agent 的人设与上下文全丢。现统一经 `_build_chat_history` 注入 |
| `chat()`（阻塞）历史入参类型标注为 `dict`，实际收到 `MessageBase` 对象 | `hist_msg["role"]` 对 Pydantic 对象直接 `TypeError`。`_build_chat_history` 同时兼容两种形态 |
| 前端回传的历史**含当前提问** | 与 `{input}` 重复注入，同一问题在上下文出现两次。按内容去重 |
| 带工具路径 token 记账恒为 0 | 注释写的是「ReAct Agent 暂不精确统计」。现按**多轮调用累加**，实测一轮 input≈7.3k |
| `done` 事件回传 LangChain `chunk` 对象 | 不可 JSON 序列化，且其 `content` 只是最后一块 |
| 前端错误消息**被抽出消息流置顶** | `ChatContainer` 把所有 `is_error` 消息从数组里过滤出来、统一渲染成 `Alert` 放在容器顶部，与发生位置脱节；长会话滚动到底时甚至不在视口内。而 `MessageBubble` 里**本就写好了** `message-content.error` 样式分支（死代码）。现改为原序内联渲染 |
| 错误标题硬编码「模型调用失败」 | 认证/限流/工具装配失败并非模型问题。现按 `error_code` 映射标题 |

### 8.7.5 实测证据

```
① 服务层（真实模型 + 真实 GitHub）
   事件统计 {'message': 840, 'done': 1} ／ 错误事件 无
   done 用量 prompt=7261 completion=519 total=7780
   正文含真实仓库名与 star 数 ✅

② HTTP/SSE 层（真实接口，复现用户操作路径）
   HTTP 200 | content-type=text/event-stream
   事件统计 {'message': 606, 'done': 1}
   落库消息 ['user','assistant'] ／ 验证用会话已清理

③ 错误分类（注入装配故障）
   → {'error_code': 'AGENT_ASSEMBLY_ERROR', 'error': '智能体执行失败：工具调用智能体装配失败：模拟故障'}
   断言「不含『模型调用失败』」通过 ✅

④ 无工具路径未受影响（超级旅游助手对话正常）

⑤ 后端全量 596 passed ／ 前端 tsc 0 错误 + vitest 26 passed
```

### 8.7.6 遗留与边界

- **依赖模型的 function calling 能力**。模型不支持时 `_build_tool_agent_executor` 会 fail-fast 抛 `AgentAssemblyError` 并给出明确提示，而不是运行到一半才崩。当前供应商 `openai`（`ChatOpenAI`）与 `ollama`/`anthropic` 分支均具备 `bind_tools`。
- **工具中间步骤未对前端可见**。`_iter_tool_agent_output` 已产出 `tool_start`/`tool_end` 事件，但 SSE 契约与前端尚无对应渲染，暂在服务层跳过；后续可加「正在调用工具 X」提示。
- `plugin_func` 的结构化分支依赖闭包默认参数（`_plugin=plugin`），**新增关键字参数前需确认不会与端点字段重名**。

### 8.7.7 验证命令（复跑）

```bash
# 后端（M1 修复 + 工具结构化回归守卫）
cd backend && .venv/bin/python -m pytest tests/test_plugin_m1_fixes.py -q --basetemp=.pytest-tmp

# 前端
cd frontend && npx tsc --noEmit && npx vitest run \
    src/pages/Agents/agentToolBinding.test.ts src/pages/Plugins/pluginMeta.test.ts
```

---

## 附录 · 关键文件索引

| 层 | 文件 |
|----|------|
| 类型体系 | `backend/app/core/plugin_source_types.py`（M2.0 由 `plugin_types.py` 更名，`plugin_type` 已移除） |
| 暴露策略 | `backend/app/core/plugin_policy.py` |
| 数据模型 | `backend/app/models/plugin.py` |
| 接口契约 | `backend/app/schemas/plugin.py` |
| 路由 | `backend/app/api/plugin.py`、`backend/app/api/agent.py` |
| 服务 | `backend/app/services/plugin.py`、`backend/app/services/agent.py` |
| 执行器 | `backend/app/utils/plugin_executor.py` |
| 出站护栏 | `backend/app/utils/net_guard.py` |
| 前端 | `frontend/src/pages/Plugins/PluginList.tsx`、`PluginConfig.tsx`、`pluginMeta.ts`、`pages/Agents/AgentForm.tsx`、`pages/Agents/agentToolBinding.ts` |
| 类型口径文档 | `docs/plugin-types.md` |
| 实施计划 | `docs/plugin-m2-m3-implementation-plan.md` |
