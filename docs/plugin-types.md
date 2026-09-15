# 插件类型语义（Plugin Types）

> 面向开发者与使用者的插件分类说明。本文是插件形态口径的权威来源，需与
> `backend/app/core/plugin_source_types.py`、`frontend/src/pages/Plugins/pluginMeta.ts`
> 保持一致。
>
> **M2.0 变更（2026-09-14）**：已移除「能力形态」维度 `plugin_type`
> （`tool` / `connector` / `processor`）。插件形态此后由**接入方式 `source_type` 单一维度**
> 承载。移除理由见 §3，完整历史记录见 §8。

---

## 1. 核心结论：单一形态维度

插件的形态由**一个**维度描述——它「怎么接进来」：

| 维度 | 字段 | 回答的问题 | 取值 |
|------|------|-----------|------|
| 接入方式 | `source_type` | 插件**怎么接进来** | `http` / `mcp` / `skill` |

> 早期版本另有「能力形态」维度 `plugin_type`（`tool` / `connector` / `processor`）。
> 该维度已确认立不住并整体移除，详见 §3 与 §8。**不要再新增与之等价的字段。**

---

## 2. 接入方式（`source_type`）

描述插件**以何种协议/封装形态**接入平台，决定它「怎么被加载与调用」。

### 2.1 `http`（HTTP / OpenAPI）

- **定位**：通过标准 HTTP 端点接入，支持用 OpenAPI/Swagger 规范自动解析端点。
- **实现状态**：**当前唯一已落地的接入方式**，由 `app/utils/plugin_executor.py` 执行。
- **使用场景**：绝大多数 REST 服务；也是当前唯一可被授权给 Agent 的来源（见 §6.2）。

### 2.2 `mcp`（Model Context Protocol）

- **定位**：通过 MCP 协议接入外部能力服务器。一个 MCP 服务通常会**暴露多个工具**。
- **实现状态**：**类型占位**。MCP 客户端、工具动态发现与注册实现属 M2.3/M2.4（见 §7）。
- **使用场景**：接入已支持 MCP 的第三方能力服务器、本地 stdio 能力进程。

### 2.3 `skill`（Skill 技能包）

- **定位**：本地技能包——说明文档 + 可选脚本/资源，由 Agent 按需加载。
- **实现状态**：**类型占位**。沙箱执行与技能加载实现属二期。
- **使用场景**：把一组操作手册与脚本打包交给 Agent。

---

## 3. 为什么 MCP / Skill 是「接入方式」而非「能力形态」

`mcp` 与 `skill` 之所以归入本题维度，而不是与 `tool` 并列：

1. **抽象层级不同**。`tool` 回答「做什么」，`mcp` / `skill` 回答「怎么接」。
   把两者压进同一枚举会造成分类轴混乱。
2. **MCP 是协议，会放大出多个能力**。把它与 `tool` 并列会导致语义矛盾
   （「这个插件是 MCP 类型，却产出 tool」）。
3. **Skill 是聚合单元**。它是能力包，天然高于单个工具。

**移除 `plugin_type` 的三条依据**（M2.0）：

1. **边界不可判定**——同一插件可同时满足多个取值：调外部 API 做摘要既是 `tool` 又是
   `processor`；查数据库既是 `connector` 又是 `tool`。原文档判据只有「以…为主」这类程度描述，
   没有可执行规则。
2. **零行为差异**——全仓**不存在任何 `if plugin_type ==` 执行分支**，它只用于列表筛选与展示；
   即无论选哪个，系统行为完全一致。
3. **定义混入了别的维度**——`connector` 的定义写进「地址、凭据、协议」，那是**接入方式**的
   职责；`processor` 写「不依赖外部系统」，同属接入维度。这与「所有插件都要配 `base_url`」
   是同一病根：把传输前提渗进了能力定义层。

对照 MCP 自身的「工具 / 资源 / 提示词」三分是**有名有实**的（调用方法、授权语义、
上下文注入方式都不同）；本项目原三分只贴了标签，没有对应任何差异。

> 历史遗留：更早还有取值 `provider`（能力供应方），因与平台 AI 供应商模块
> （`/api/ai-providers`）语义重叠而先行移除，历史记录由迁移 `a7b8c9d0e1f2` 改写为
> `connector`；`connector` 亦已随 `plugin_type` 一并移除。

---

## 4. 与 Agent 工具（Tool Calling）的关系

**「插件能否被 Agent 调用」与「插件形态」无关。**

在 `backend/app/services/agent.py` 中，Agent 通过工具项 `tool_type == "plugin"` 挂载插件，
运行时会取出该插件的端点并包装成 LangChain 工具。也就是说：

- 插件的端点能否被注册为 Agent 工具，取决于**授权**与**运行时门禁**，与形态标签无关；
- 所有插件的执行统一由接入方式对应的适配器处理（当前仅 `source_type=http` 有实现）。

> **能注册 ≠ 任何插件都会进工具池**。授权发生在**设计期**：用户创建/编辑 Agent 时从服务端
> 裁剪过的候选目录中显式挑选「插件 → 端点」，未选中的插件既不进入工具池，也不占用模型上下文。
> 运行时另有一层纵深防御。详见 §6。

---

## 5. 数据与接口

### 5.1 数据模型

`plugins` 表：

| 字段 | 类型 | 说明 |
|------|------|------|
| `source_type` | String(50) | 接入方式：`http/mcp/skill`，默认 `http` |

### 5.2 接口

- 创建/更新（`POST /plugins`、`PUT /plugins/{id}`）：`source_type` 受枚举校验，非法值返回 `422`。
- 列表（`GET /plugins`）：支持 `?source_type=...` 过滤。
- 候选目录（`GET /agent/agents/tool-catalog`）：仅返回接入方式已实现的插件，不再有形态过滤入参。

### 5.3 迁移

| 迁移 | 作用 |
|------|------|
| `a7b8c9d0e1f2_add_plugin_source_type.py` | 新增 `plugins.source_type`（默认 `http`）；历史 `plugin_type='provider'` 改写为 `connector` |
| `h2i3j4k5l6m7_drop_plugin_type.py` | **M2.0**：`DROP COLUMN plugins.plugin_type`；`downgrade` 仅恢复列结构（默认 `tool`），不还原历史取值 |

---

## 6. Agent 工具授权：设计期为主控，运行时为兜底

### 6.1 控制点应放在哪一层

早期实现把控制点放错了位置：`agent_tools` 只是「绑定记录」，绑定之后运行时**没有任何判据**；
同时前端也**没有选择入口**——`AgentForm.tsx` 里没有任何工具配置区，`tools` 只能通过 API 直写，
且写入时不校验。结果两头失控：

- 前端建出的 Agent **工具集恒为空**（漏配）；
- API 直写可挂上 `disabled` 插件、他租户插件或不存在的端点（错配）。

正确的结构是四层，**主控点在设计期**：

| 层 | 职责 | 实现 |
|----|------|------|
| 候选目录 | 服务端裁剪「你能选什么」 | `PluginService.list_bindable_for_agent` + `GET /api/agent/agents/tool-catalog` |
| **设计期选择（主控）** | 用户显式挑选「插件 → 端点」 | `frontend/src/pages/Agents/AgentForm.tsx` + `agentToolBinding.ts` |
| 授权清单 | `agent_tools` 条目集合 = 该 Agent 的能力边界 | `AgentService.create_agent / update_agent` |
| 运行时门禁（兜底） | 防清单在保存后被外部改坏 | §6.5 |

运行时门禁**无法替代**设计期授权：它只能「跳过」非法工具，既无法让用户**选到**正确的工具，
也无法解决「注入一堆用不到的插件」——那属于选择面的问题。

### 6.2 候选目录：服务端裁剪，前端只展示

`GET /api/agent/agents/tool-catalog` 返回可授权清单，裁剪条件与写入校验**共用同一判据**
（`plugin_policy.check_plugin_bindable`），避免「选得到却存不下」或「存得下却选不到」：

| 条件 | 取值 | 理由 |
|------|------|------|
| 归属 | 本租户 或 平台公共插件（`tenant_id IS NULL`） | 租户隔离 |
| 状态 | `active` | `disabled` / `pending_review` 不该出现在候选中 |
| 接入方式 | `http` | `mcp` / `skill` 执行器尚未落地，放进候选等于让用户选到跑不通的项 |
| 端点 | ≥ 1 | 无端点即无可授权的内容 |

端点按插件批量查出后分组，避免 N+1。前端**不重复判断「是否可用」**，否则两端口径会漂移。

> ⚠️ **路由顺序**：`/agents/tool-catalog` 必须声明在 `/agents/{agent_id}` **之前**。
> FastAPI 按注册顺序匹配，否则会被当作 `agent_id="tool-catalog"` 吞掉。

### 6.3 设计期选择：粒度到端点

**授权单位是「插件 + 端点」，不是插件。** 可调用性的原子单位是 endpoint——只选插件会让
「暴露了哪些具体操作」对用户不可见，也无法精确拦截高危端点。

- 候选以插件分组展示，每个端点显示 `METHOD /path`，破坏性端点带红色 `破坏性` 标签；
- 破坏性端点**默认隐藏**，需开启「显示破坏性端点」开关才可见；
- 勾选破坏性端点触发**二次确认**，确认后才写入 `allow_destructive: true`——即「勾选动作
  本身就是一次显式授权」，后端门禁因此仍具约束力，而不是被前端悄悄绕过；
- 目录中已失效的授权（插件被删除/停用、端点被移除）以告警提示用户重新选择，而非静默丢弃
  ——静默丢弃正是「失效授权无声扩散」的成因。

**工具名生成必须 ASCII 安全**：`name` 会作为 function name 传给模型，OpenAI 兼容接口要求
`^[a-zA-Z0-9_-]{1,64}$`，而插件名常为中文。因此 `name` 走 sanitize（中文名退回
`plugin-{id 前 8 位}`），可读的中文描述放进 `description`——模型靠描述而非名字选择工具。

### 6.4 写入校验：fail-closed 整体拒绝

`AgentService._validate_tool_bindings` 在落库前校验全部 `plugin` 类工具：

- 插件须属于当前租户或为公共插件，否则拒绝；
- 状态、接入方式、端点数量须通过 `check_plugin_bindable`；
- 须解析到有效端点（`resolve_bound_endpoint`），**不存在「未指定则取第一个」的兜底**；
- 破坏性动词须已显式放行。

**任一条不合法即抛 `ValidationException`，整次请求失败**，而非逐条跳过。部分成功会让调用方
无法判断最终状态，也容易掩盖「以为配上了、其实被静默丢弃」。更新路径上，校验先于删除旧工具执行。

> 只校验 `plugin` 类型。`knowledge` / `api` / `function` / `workflow` 各有自己的配置约束，
> 不属本策略范围。

### 6.5 运行时门禁（纵深防御）

设计期已把控制点前移，运行时门禁的作用随之收窄为**兜底**：防止授权清单在保存之后被外部改坏
——插件被停用、接入方式被改成未实现的取值、端点被删除、`base_url` 被改指内网。

规则集中定义于 `backend/app/core/plugin_policy.py`（纯函数，便于单测）：

| # | 门禁 | 判据 | 不通过时 |
|---|------|------|---------|
| 1 | 状态门禁 | `plugin.status == "active"` | 跳过；`disabled` / `pending_review` 一律不暴露 |
| 2 | 接入方式门禁 | `plugin.source_type` ∈ 已实现适配器的来源（当前仅 `http`） | 跳过；`mcp` / `skill` 执行器未落地，不暴露 |
| 3 | 端点门禁 | 工具配置显式给出 `endpoint_id` 或 `endpoint` | 跳过（**不回退到首个端点**） |
| 4 | 动词门禁 | 非 `DELETE` / `PUT` / `PATCH`，或显式 `allow_destructive: true` | 跳过（破坏性动词默认不暴露） |

门禁遵循 **fail-closed**：任何判据不通过即**跳过该工具并记录告警**，而非放行。

> 第 1、2 条与设计期候选裁剪**共用同一份取值集合**（`AGENT_EXPOSABLE_PLUGIN_STATUSES` /
> `BINDABLE_SOURCE_TYPES`），避免「选得到却跑不通」的口径分裂。

> 显式放行开关 `allow_destructive` 取值必须为布尔 `true`；字符串 `"true"` 不算放行，
> 避免配置误填静默绕过门禁。
> `POST` 未纳入本门禁——语义过于宽泛，一刀切会误伤大量正常端点；该类风险由「端点选择」
> 与后续的人工确认（HITL）承接。

运行时解析端点与设计期校验**共用 `resolve_bound_endpoint`**，避免两处规则漂移；
同时复用 `PluginService.get` 已加载的端点，省去两次按端点查询。

### 6.6 出站安全护栏（SSRF 防护）

实现于 `backend/app/utils/net_guard.py`，在 `plugin_executor` 发起请求前对
**最终 URL**（路径参数替换之后）校验：

| 检查项 | 规则 |
|--------|------|
| 协议 | 仅 `http` / `https` |
| 主机名 | 拒绝 `localhost` 及其子域 |
| IP 范围 | 拒绝私有、环回、链路本地（含 `169.254.169.254`）、保留、组播、未指定、IPv6 站点本地，以及 `100.64.0.0/10`（CGNAT，`ipaddress` 的标志位未覆盖，需显式列出） |
| 解析失败 | 即拒绝（fail-closed） |
| 重定向 | 不跟随（重定向可绕过校验目标） |
| 路径参数 | 做 URL 编码，参数无法借 `../` 或 `//host` 改写请求目标 |

IPv4-mapped IPv6（形如 `::ffff:127.0.0.1`）会先还原为 IPv4 再判断，否则会被误判为公网地址。

同一护栏也作用于 Agent 的 **API 工具**（`tool_type="api"`）——该工具的目标 URL 同样由租户配置，
风险同源。

**配置**：`PLUGIN_BLOCK_PRIVATE_NETWORK`（默认 `true`）。确需让插件访问内网服务
（如对接内部 CRM）时应显式置为 `false`——这是一次**有意识的降级**，须同时通过网络层
出站策略限制可达范围，不能仅依赖应用层。

**残留风险**：校验与建连之间存在 DNS 重绑定（TOCTOU）窗口。彻底消除需在连接层固定
已校验 IP 或统一走 egress 代理，属二期（见 §7）。

### 6.7 行为变更提示

- 此前「只配 `plugin_id`、不配端点」的绑定**将不再生效**。若 Agent 的工具未如期调用，
  请检查日志中的 `Agent 插件工具跳过：...` 告警，按提示补齐 `endpoint_id` 或 `endpoint`。
- 指向内网地址的既有插件/API 工具在升级后会调用失败。确属内网对接需求时，
  再评估是否关闭 `PLUGIN_BLOCK_PRIVATE_NETWORK`。
- **新增**：Agent 表单现可选择工具。此前通过 UI 创建的 Agent 工具集为空，进入编辑页
  重新勾选即可补齐；通过 API 直写、只带 `endpoint` 路径而无 `endpoint_id` 的历史记录，
  会在编辑页按路径自动匹配回填。
- **M2.0**：创建/更新插件不再接受 `plugin_type` 字段（多余入参被忽略）；列表接口不再有
  `plugin_type` 过滤参数；工具目录不再回显形态。

### 6.8 验收用例

| 测试 | 用例数 | 覆盖 |
|------|--------|------|
| `backend/tests/test_plugin_source_types.py` | 13 | 接入方式取值与 Schema 校验、元数据完整性；**`plugin_type` 移除守卫**（旧模块不可导入、Schema 不再落该字段、ORM 无该列、`PluginOut` 无该字段） |
| `backend/tests/test_plugin_m1_fixes.py` | 16 | M1 修复回归（凭据加密、配置写入契约、参数 schema 接线等） |
| `backend/tests/test_plugin_governance.py` | 61 | 运行时门禁（状态/接入方式/端点/动词）与 SSRF 护栏（环回、私网、链路本地、元数据、`100.64.0.0/10`、非 http 协议、路径参数编码、降级开关） |
| `backend/tests/test_agent_tool_catalog.py` | 32 | 候选裁剪四类（非 active / 未实现接入方式 / 无端点 / 归属）、端点解析**不做隐式兜底**、写入校验 fail-closed 且能定位到具体工具、目录端点分组与「无端点即排除」 |
| `frontend/src/pages/Plugins/pluginMeta.test.ts` | 7 | 接入方式元数据/选项派生、未知取值降级、原型链键防护；**`PLUGIN_TYPE_*` 导出已移除守卫** |
| `frontend/src/pages/Agents/agentToolBinding.test.ts` | 19 | 选择项 ↔ 工具载荷互转、ASCII 安全命名、破坏性端点标注与放行、失效授权识别、历史数据回填 |

关键回归保护：**`resolve_bound_endpoint` 在未指定端点时必须返回 `None`，不得取第一个端点**。

---

## 7. 后续演进

| 项 | 现状 | 计划 |
|----|------|------|
| `http` 接入 | 已实现 | — |
| `mcp` 接入 | 类型占位 | M2.3/M2.4：MCP 客户端（stdio + streamable-http）+ 工具动态发现与注册 + stdio 沙箱 |
| `skill` 接入 | 类型占位 | 二期：技能包加载 + 沙箱执行 |
| 接入声明分层 | 单表 + `api_spec` 列 | M2.1/M2.2：按 `source_type` 建接入声明子表 + `plugin_capabilities`，新增 `PluginAdapter` 注册表 |
| **设计期授权**（候选目录 + 端点粒度选择 + 写入校验） | **已实现** | — |
| 状态 / 接入方式 / 端点 / 动词门禁 | **已实现** | — |
| 出站 SSRF 护栏 | **已实现** | 二期：连接层固定 IP 或统一 egress 代理，消除 DNS 重绑定窗口 |
| 工具命名空间（`{plugin}_{capability}`） | 未实现 | M3.1 |
| 工具数量超限的按需加载 | 未实现 | M3.2 |
| 单 Agent 能力预览页 | 未实现 | P1：在 Agent 详情/对话页展示「该 Agent 能触达哪些外部系统」 |
| 租户级插件启用 | 未实现 | P1：插件「存在」与「对本租户可用」解耦，候选目录按启用状态进一步裁剪 |
| 调用审计与配额 | 未实现 | M3.3：记录 agent / tool / plugin / endpoint / 动词 / 入参摘要 / 状态码 / 耗时，并计入 `QuotaService` |
| 参数 Schema 校验 | 未实现 | P1：命中 `request_body_schema` 时做 JSON Schema 校验 |
| 高风险端点 HITL | 未实现 | P2：涉及资金/发送/删除的端点，调用前需人工确认 |

> 在 MCP / Skill 执行器落地前，建议仅将 `source_type` 设为 `http`；选择 `mcp`/`skill`
> 时前端已有 Tooltip 提示「执行器实现属二期」。

---

## 8. 已移除：能力形态 `plugin_type`（历史记录）

| 项 | 内容 |
|----|------|
| 移除时间 | 2026-09-14（M2.0） |
| 原取值 | `tool` / `connector` / `processor`（更早还有已废弃的 `provider`） |
| 移除依据 | 边界不可判定、零行为差异（无 `if plugin_type ==` 分支）、定义混入接入方式维度（见 §3） |
| 迁移 | `h2i3j4k5l6m7_drop_plugin_type.py`（`DROP COLUMN plugins.plugin_type`） |
| 模块变更 | `app/core/plugin_types.py` → `app/core/plugin_source_types.py`（仅保留 `source_type` 口径） |
| 前端变更 | 移除 `PluginType` 类型、`PLUGIN_TYPE_META`、`PLUGIN_TYPE_OPTIONS`、`pluginTypeMeta()` 与列表/表单/详情中的形态展示 |
| 接口变更 | 创建/更新不再接受 `plugin_type`；`GET /plugins` 移除 `plugin_type` 过滤参数；`tool-catalog` 不再回显形态 |
| 数据影响 | 列被删除，原取值**不保留**；该列无行为语义，如需还原请从迁移前备份恢复 |

配套决策记录：`docs/plugin-capability-model-design.md` §2.4、§7；
实施计划：`docs/plugin-m2-m3-implementation-plan.md` M2.0。
