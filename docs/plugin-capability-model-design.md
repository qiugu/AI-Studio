# 插件能力模型设计方案（对照社区最佳实践）

> **文档性质**：设计方案 · **待评审**。
> 本文只给出目标模型、方案对比与实施路线，**不含任何代码改动**。按项目约定，需经评审确认后方可进入实施。
>
> **前置阅读**：[plugin-usage-flow-review.md](plugin-usage-flow-review.md) §7「能力模型的覆盖面诊断」——本文承接其 §7.1 提出的问题，给出社区基准对照下的完整设计。
>
> **一句话结论**：当前设计的根本偏差在于把「接入方式」当作了一个**标签列**（`source_type`），而社区共识是它必须是一个**分派键**——因为它唯一决定了「发现机制、存储结构、凭据形态、执行路径、安全边界」这五件事。

---

## 1. 社区最佳实践基准

本方案以三个成熟的、可交叉验证的参照系为准，而非个人偏好。

### 1.1 参照系一：MCP 规范——能力是运行时的，协议是传输无关的

MCP（Model Context Protocol，Anthropic 2024-11 发布，治理已移交 Linux Foundation 的 Agentic AI Foundation）的关键设计约束：

| 约束 | 内容 | 对本项目的含义 |
|------|------|--------------|
| **原语抽象** | 服务端暴露三类原语：`tools`（可调用动作）、`resources`（只读数据）、`prompts`（模板）。工具结构为 `{name, description, inputSchema, outputSchema?, annotations?}` | 能力的最小表示是「名字 + 语义描述 + 输入 Schema」，**不是**「路径 + 动词」 |
| **运行时发现** | 能力清单由 `tools/list` 在**会话期**获取，支持游标分页；服务端可发 `notifications/tools/list_changed` 通知刷新 | **注册时无法预知端点列表**——这与「NOT NULL 的 path/method + 至少 1 个端点」的判据在模型层直接冲突 |
| **传输无关** | 标准传输两种：`stdio`（客户端派生子进程，stdin/stdout 传 JSON-RPC）与 `Streamable HTTP`（单一端点，POST + 可选 SSE 流）；2025-03-26 修订以 Streamable HTTP 取代旧的 HTTP+SSE | 「连接方式」是传输层的属性，不是能力的属性 |
| **无状态核心（2026-07-28 修订）** | 取消 `initialize` 握手与协议会话；每个请求在 `_meta` 中携带协议版本、客户端身份与能力；`server/discover` 用于探测服务端能力 | 客户端实现更简单，**但仍必须持有「服务身份 + 凭据 + 传输配置」这一层持久状态** |
| **能力协商** | 双方在握手期声明各自支持的能力，未声明者不应被请求；不支持时应拒绝而非静默降级 | 「门禁」应当按能力声明走，而不是全局硬编码 |

> 来源：MCP Specification（2025-06-18 / 2026-07-28 修订）、`modelcontextprotocol.io`、各 SDK 与第三方解析文章（详见 §8 参考）。

**关键推论**：MCP 里根本没有"端点表"这个概念。它的等价物是**运行时可发现、可动态变更的能力清单**。因此把 MCP 塞进 `plugin_endpoints`（path/method NOT NULL）不是"缺一个执行器"的问题，而是**模型层面的不可表达**。

### 1.2 参照系二：Dify `ToolProviderType`——接入方式决定四条链路

Dify 是当前开源生态中插件/工具接入体系最完整、且被大规模生产验证的实现。它的做法是把"工具来源"提升为**顶层类型分派**：

| Provider 类型 | 发现方式 | 存储模型 / Schema 来源 | 凭据 | 多租户 |
|--------------|---------|---------------------|------|--------|
| `BUILT_IN` | 文件系统 / 硬编码 | Python 类，随平台分发 | 每租户多组凭据 | 每租户凭据 |
| `API` | 用户创建 | `ApiToolProvider` + OpenAPI/Swagger 解析 | `credentials_str`（**加密**） | 租户内 |
| `WORKFLOW` | 已发布工作流 | `WorkflowToolProvider` + 工作流图 | — | 租户内 |
| `PLUGIN` | 插件市场 | 插件清单 + 守护进程 | 每租户凭据 | 每租户凭据 |
| `MCP` | **MCP 协议发现** | `MCPToolProvider` + MCP 协议 | 每租户凭据 + OAuth | 租户内 |
| `DATASET_RETRIEVAL` | 知识库 | 数据集元数据 | — | 租户内 |

架构上由 `ToolManager`（单例注册表 + 工厂）与 `ToolProviderController`（策略接口）承载：`get_tool_runtime()` 按 provider 类型分派到不同的 runtime 实现。**每种类型有独立的发现、凭据与调用模式。**

> 来源：langgenius/dify DeepWiki「Tool Provider Types and Architecture」、`api/core/tools/tool_manager.py`、`api/models/tools.py`。

**关键推论**：Dify 中 `BUILT_IN` 与 `DATASET_RETRIEVAL` **完全不需要 `base_url`**，也完全不需要网络。这说明"插件/工具"的一级分类轴是**来源类型**，而不是"是否外部 HTTP"。本项目的 `plugin_type`（tool/connector/processor）在 Dify 中没有对应物——因为它不是分派轴，而是贴在同一实现上的语义标签（见 review §4.4 已核实的结论）。

### 1.3 参照系三：Anthropic 工具设计准则——工具契约面向模型，而非面向 API 端点

Anthropic 工程团队在《Writing effective tools for agents》（2025-09，并由 Applied AI 团队在 2026 年进一步阐述）中给出的一线结论：

| 准则 | 内容 |
|------|------|
| **意图驱动合并** | 反对"每个 API 端点包一个工具"的薄封装反模式。举例：用 `schedule_event` 取代 `list_users` + `list_events` + `create_event`；用 `search_logs` 取代 `read_logs`；用 `get_customer_context` 取代 `get_customer_by_id` + `list_transactions` + `list_notes` |
| **命名空间** | 按服务与资源加前缀（`asana_search`、`jira_search`），在工具数量增长时划定清晰边界。前缀 vs 后缀的效果因模型而异，需实测 |
| **返回高信号上下文** | 用自然语言名称替代 UUID；提供 `response_format` 枚举让模型自行控制输出详略（实测一条 Slack 线程响应从 206 token 降到 72） |
| **描述即入职文档** | 参数描述、用法示例、边界条件应与 system prompt 同等严格。"若人类工程师都无法确定该用哪个工具，模型更不可能" |
| **评估驱动迭代** | 原型 → 50+ 真实任务评估 → 分析推理过程而非仅看准确率 → 迭代 |

> 来源：`anthropic.com/engineering/writing-tools-for-agents`；第三方综述见 §8。

**关键推论**：这条准则对当前缺口的修法提出了比"接线 `request_body_schema`"更高的要求——**接线只是第一步；工具应当按意图组织，而非按端点组织。** 但这是产品决策，不是技术必选项，故列入 §7 待决策项。

### 1.4 三家共识

三个参照系在一点上完全一致：

> **「能力做什么」（对模型暴露的契约）与「怎么连上去」（传输、发现、凭据、安全）是两个独立维度，且后者必须可多态分派。**

本项目已经**部分**做对了这件事（见 §2.2），但把多态的实现方式落在了"一个枚举列"上，而非"一条分派链路"上。

---

## 2. 对照诊断

### 2.1 逐维度比对

| 维度 | 当前实现 | 社区基准 | 判定 |
|------|---------|---------|------|
| 接入方式 | `plugins.source_type` 枚举列，**无任何行为分派**（review §4.4 已核实：全仓无 `if source_type ==` 执行分支） | 分派键 → 策略/Adapter | **偏差** |
| 能力表示 | `plugin_endpoints`：`endpoint`(路径) / `method` 均 `NOT NULL` | 来源无关的能力抽象（name / description / inputSchema / annotations） | **偏差** |
| 能力发现 | 注册时静态写入数据库 | HTTP = 规范解析（静态）；MCP = 运行时探测 + 缓存（动态） | **偏差** |
| 执行 | `httpx` 同步请求硬编码在 `plugin_executor.py` | 按来源分派 executor | **偏差**（已知，二期） |
| 凭据 | `plugin_configs`：形态无关 JSON + `config_schema` 驱动渲染 | per-tenant credentials | **方向正确**（缺加密） |
| 授权 | `agent_tools`：`tool_type` 判别 + 通用 `config` JSON | 服务级授权 + 工具过滤 | **方向正确** |
| 工具契约 | 端点 `request_body_schema` 声明但未接线；模型只见 `query: str` | 面向模型的完整契约 | **偏差** |

### 2.2 已经正确的两层（且是最难改的两层）

需要明确指出：**凭据层与授权层已经是形态无关的，这恰恰是社区实践中迁移成本最高、最容易做错的两层。**

**凭据层** `plugin_configs`：`{plugin_id, tenant_id, name, value(JSON)}` + `plugins.config_schema`。任意形态的接入参数都能容纳（MCP 的 `command`/`args`/`env` 是普通 JSON）。这一点由 review §7.2 的逐字段试填已证实。

**授权层** `agent_tools`：`{tenant_id, agent_id, tool_type, config(JSON), name, description, is_enabled}`。核对 `models/agent_tool.py:21-30` 可见，plugin 类绑定把 `{plugin_id, endpoint}` 放在通用 `config` JSON 中：

```
# plugin: {"plugin_id": ..., "endpoint": "search"}
config: Mapped[dict] = mapped_column(JSON, nullable=False)
```

**这意味着授权层无需任何表结构改动即可承载 MCP/skill 的绑定**，只需扩展 `config` 的语义约定（见 §3.5）。这是一个显著有利的既成事实，应作为方案设计的基线约束予以保留。

> 顺带发现一处文档陈旧：`models/agent_tool.py:29` 的注释仍写作 `{"plugin_id": 1, ...}`（整型），而核心业务 ID 已统一为字符串 UUID v4（见 AGENTS.md）。属注释未随迁移更新，建议在实施时一并修正。

### 2.3 根因

> **把某一种协议的形态当成了插件的形态。**

具体表现为三处"放错位置"的约束：

1. `plugin_endpoints.endpoint` / `method` 的 `NOT NULL` —— 把 HTTP 的约束放在了**能力表**上。正确位置是 HTTP Adapter 的校验逻辑。
2. `check_plugin_bindable` 的 `endpoint_count <= 0` 判据（`core/plugin_policy.py:126-127`）—— 把"必须静态可见"当成了可绑定的前提。对运行时发现的来源不成立。
3. `_resolve_base_url` 的必需性（`utils/plugin_executor.py:110-112`）—— 把 HTTP 的寻址需求当成了插件的通用需求。

### 2.4 附论：`plugin_type` 三分法的复核

**问题**：既然工程分派轴应当是 `source_type`，那 `plugin_type` 的 `tool` / `connector` / `processor` 三分法是否是错误的架构？

**结论**：**分类轴本身不算错**——它是真实存在的语义维，MCP 的三类原语（`tools` / `resources` / `prompts`）是其权威表达。**错误在于四点落地方式，其中只有第 4 点与 `source_type` 有直接关系。**

回答前必须先分开两件常被混为一谈的命题：

| 命题 | 判定 |
|------|------|
| 一：插件系统的**工程分派轴**应当是 `source_type` | **成立**（见 §1、§3.2） |
| 二：`plugin_type` 三分法**本身**是错误分类 | **不成立** |

**命题一成立不蕴含命题二。** 三分法的问题出在它自己内部，与"分派轴该放哪"是两个独立议题。

#### 四点错位（均有文档证据）

**错位 1 · `connector` 的定义里写进了接入机制**

- `docs/plugin-types.md:45`：「维持与外部系统之间的连接语义（**地址、凭据、协议**）」
- `docs/plugin-types.md:49`：「通常需要较多的连接配置（**`base_url` / `api_key`** 等）」

地址、凭据、协议是 `source_type` 的职责。**HTTP 前提渗进了能力形态的定义层**——与"base_url 适用场景太小"是同一病根。

**错位 2 · `processor` 的定义与文档自己的例子矛盾**

- `docs/plugin-types.md:54`（§2.3）：「在**不依赖外部系统**的前提下，把一类数据变换成另一类数据」
- `docs/plugin-types.md:22`（§1）：「一个「文本摘要」能力可以是 `processor + http`」

"是否依赖外部系统"是**接入维度**的属性，不是能力形态的属性。文档一边把它写进 `processor` 的定义，一边举 `processor + http` 的例子。

**错位 3 · 三个取值之间没有可判定的边界**

文档给出的判据全部是程度描述，而非规则：

| 取值 | 文档判据 | 出处 |
|------|---------|------|
| `tool` | 「只做一件事」 | `plugin-types.md:40` |
| `connector` | 「强调『连上一个系统』」 | `plugin-types.md:49` |
| `processor` | 「以『变换』为主」 | `plugin-types.md:57` |

反例即可证伪：「调用外部 API 做文本摘要」是 `tool`（发起 HTTP 请求）还是 `processor`（输入→输出变换）？「查询数据库」是 `connector`（连上一个系统）还是 `tool`（单个动作）？**两者都无法按规则判定。**

更绝对的是，`tool` 的定义直接写死了传输形态——`backend/app/core/plugin_types.py:7`：「原子化、可被 Agent 调用的单个动作（**HTTP 端点**）」——这等于把 MCP 的 tool 从 `tool` 里排除掉了。

**错位 4 · 声明了行为差异却零实现（唯一与 `source_type` 相关的错位）**

- `docs/plugin-types.md:121`：「`plugin_type` 当前**仅用于分类展示与列表过滤**，不决定任何执行行为」
- `docs/plugin-types.md:120`：「任何插件（不论 `plugin_type` 是 tool / connector / processor）的端点都可以被注册为 Agent 工具」
- `docs/plugin-types.md:308`：「类型差异化校验 | 仅枚举校验 | 可为各类型补充必需的 `config_schema` / 端点约束」

文档自己承认了零行为差异。**反证在 MCP**：其三原语对应**三种不同的调用方法**（`tools/call` / `resources/read` / `prompts/get`）、不同的授权语义与不同的上下文注入方式。**可见这类三分法完全可以有行为差异——本项目缺的恰恰是这个。** 所以这不是"三分法不该存在"，而是"它在这里名实不符"。

#### 须澄清：两个维度当前都没有分派

容易误读为"一个对一个错"。实际是：

| 维度 | 应当 | 实际 |
|------|------|------|
| `source_type` | **分派键**：决定发现 / 存储 / 执行 / 护栏 | **未分派**。仅作为 `BINDABLE_SOURCE_TYPES` 的一个硬编码门禁集合（`core/plugin_policy.py:105`），全仓无 `if source_type ==` 执行分支 |
| `plugin_type` | 语义角色，**不参与**工程分派 | **未分派，且不应分派**。问题在定义混乱与位置误导，不在"缺少分支" |

#### 三个处理选项

| 选项 | 做法 | 优点 | 代价 |
|------|------|------|------|
| **1 · 保留并兑现**（推荐） | 收敛到**一条**真实行为差异：**该能力能否被 Agent 直接调用**（对应 MCP 的 `tools` vs `resources`）。`tool` / `processor` 进 Agent 工具池；`connector` 提供上下文而非可调用动作 | 三分法从"展示标签"变为"行为判据"，名实相符 | 需产品定义"数据接入型能力"的调用语义 |
| 2 · 降级为纯标签 | 承认它只是 UI 分类，不承诺行为。但必须**重写定义**（删去"地址、凭据、协议""不依赖外部系统"）并**弱化 UI 暗示** | 改动最小 | `PLUGIN_TYPE_META.use_cases`（"数据清洗、格式转换""对接数据库、企业 IM"）会持续让用户预期不同能力；见 `core/plugin_types.py:57-66` |
| 3 · 移除 | 删除 `plugin_type` | 彻底消除歧义 | 需迁移既有数据；失去一个未来可能有用的语义槽位 |

**判断选项 1 是否可行的依据——与 MCP 原语的对应强度**：

| 本项目 | MCP 原语 | 对应强度 |
|--------|---------|---------|
| `tool` | `tools` | **强**（可调用动作，语义与调用方式均一致） |
| `connector` | `resources` | **中**（均为"提供上下文而非执行动作"） |
| `processor` | — | **弱**（MCP 无"纯函数"原语，最接近者是 `tools` 中的纯计算方法） |

即：**`tool` 与 `connector` 的区分有权威依据，`processor` 是最弱的一环。** 若采纳选项 1，`processor` 是否保留为独立取值应单独评估。

### 2.5 产品定位定调：为什么只能是「多协议能力中心」

**本节回答一个问题：能否把插件定位收敛为「HTTP 工具注册中心」。** 结论是：该定位不成立，而且它不是一个可选项——它把**一个未完成态**误述成了一种方向选择。

#### （1）澄清：「HTTP 工具注册中心」从来不是设计目标，而是当前的落地状态

`core/plugin_types.py:36-42` 已经把 `source_type` 声明为三值（`http` / `mcp` / `skill`），且 `:69-85` 的 `PLUGIN_SOURCE_TYPE_META` 明确标注后两项「执行器实现属二期」。这说明：

- **设计意图自始就是多协议**——`source_type` 这一维度的存在本身，就是为了容纳不止一种接入方式；若只要 HTTP，这一列根本不必要有。
- 当前只落地 `http`，是**实现进度的差异**，不是定位选择的结果。

因此真正需要决策的从来不是「要不要多协议」，而是「**要不要兑现已经声明、且对用户可见的选项**」。把 `mcp` / `skill` 选项长期留在 UI 上而不兑现，本身就是缺陷（review §7.6 第 1 项已指出）。

#### （2）精确校正：说「Agent 只能有 HTTP 工具」不准确，但结论更强

`agent_tools.tool_type` 实际有 **5 个取值**（`models/agent_tool.py:21`），其中 **3 类非 HTTP**：

| tool_type | 执行路径 | 协议 | 是「能力注册面」吗 |
|-----------|---------|------|------------------|
| `knowledge` | `KnowledgeBaseService.search(...)`（`services/agent.py:305-323`） | 无网络 | 是，但只能登记文档 |
| `api` | 内联 `httpx` + `assert_outbound_url_allowed`（`:326-388`） | HTTP | **否**，逐 Agent 内联配置 |
| `function` | `exec()` in `safe_builtins`（`:391-457`） | 无网络 | **否**，代码内联 |
| `workflow` | `WorkflowEngine.execute_workflow(...)`（`:460-501`） | 无网络 | 是，内部编排 |
| `plugin` | `execute_plugin_call(...)`（`:504-`） | **仅 HTTP** | **是**（平台唯一的「外部能力注册面」） |

所以准确的表述是：**平台并不缺非 HTTP 工具，缺的是非 HTTP 能力的「注册面」。**

`function` / `api` 只能**逐 Agent 内联写入** `agent_tools.config`，因而不具备插件注册面提供的治理能力：

| 治理维度 | 插件注册面 | 内联旁路（`function` / `api`） |
|---------|-----------|---------------------------|
| 凭据隔离 | `plugin_configs` 租户级托管 | 无，直接写在 `agent_tools.config` |
| 复用 | 一个插件被 N 个 Agent 授权 | 无，每个 Agent 各复制一份 |
| 端点级授权 | 有（`plugin_endpoint_id`） | 无，整体启用 / 禁用 |
| 审计与配额 | 部分具备（review §3.8 已指出不足） | 无 |
| 变更影响面 | 可查 | 不可查 |

**这才是 HTTP-only 的真实代价**：它不只限制「能接什么」，还迫使所有非 HTTP 能力走内联旁路——**而旁路是没有治理的**。

#### （3）旁路的安全代价有实测证据

`function` 的沙箱并不可靠。实现见 `services/agent.py:398-429`：把 `safe_builtins` 字典作为 `__builtins__` 传给 `exec`，**仅限制内置函数名，不限制属性访问**。实测（纯属性遍历，未调用任何被禁内置函数）：

```python
def main(inp):
    subs = ().__class__.__bases__[0].__subclasses__()
    return [c.__name__ for c in subs if c.__name__ in ("Popen", "_wrap_close")]

# 实测输出：
# {'escaped': True, 'reachable': ['BuiltinImporter', 'FileLoader', '_wrap_close', 'Popen']}
```

即 `function` 工具等价于**进程内任意代码执行**。这不是 HTTP-only 直接造成的，但它印证了一条规律：**当一种能力没有正规注册面时，只能被塞进安全边界更差的旁路。** 「多协议能力中心」要解决的正是这个问题——把非 HTTP 能力收进受治理的注册面，而非任其散落于内联配置。

#### （4）HTTP 表达不了什么

| 能力类别 | 典型来源 | HTTP 可表达 | 需要的接入形态 |
|---------|---------|------------|--------------|
| 公网 SaaS 的 REST 接口 | 天气、工单、CRM | 是 | `http` |
| 已发布的 MCP 服务 | 官方 / 社区 MCP server | **否**（协议不同） | `mcp` |
| 本地 / 私有进程能力 | 本地搜索、文件系统、内部 CLI、桌面自动化 | **否** | `mcp(stdio)` 或 `skill` |
| 无网络的纯技能包 | 操作手册、模板、提示词包 | **否** | `skill` |
| 平台内检索 / 编排 | 知识库、工作流 | **否**（本就不应走 HTTP） | 内建 `knowledge` / `workflow` |

判断标准只有一条：**HTTP 是「公网可达的 SaaS」的最低公分母；而 Agent 价值密度最高的一批工具，恰恰不在公网上。**

#### （5）结论

**定位为「多协议能力中心」。** 这不是方向变更，而是**兑现既有声明**——`source_type` 的存在已表达了该意图，缺的是把它从标签列变成分派键（§3.2）。

由此，§7 待决策事项从 6 项收敛为 5 项，且剩余项全部是**执行层面的选择**，不再含方向性问题。

> **⚠️ 一条前置约束**：既然 MCP / skill 会把「本地执行」的能力引入注册面，**§5 的隔离方案必须先于 M2 主体落地**。上面 `function` 的实测就是现成反例——把本地执行从「内联代码」扩散到「平台级注册面」，若无硬隔离，风险面会被放大而非收敛。

---

## 3. 目标模型

### 3.1 五层职责划分

```
┌─ L1 身份层 ────────────────────────────────────────────────┐
│  plugins：name / description / icon / version / status      │
│           is_public / tenant_id                             │
│  · 形态无关；作为权限、授权、审计的锚点                        │
│  · 保留现状                                                 │
└────────────────────────────────────────────────────────────┘
                          │ source_type 作为【分派键】
                          ▼
┌─ L2 接入声明层（新增 · 按来源分派）─────────────────────────┐
│  http  → base_url 来源 + OpenAPI spec                      │
│  mcp   → transport(stdio | streamable_http)                │
│          + command/args/env  或  url/headers               │
│          + 可选 tool 过滤（include/exclude）                │
│  skill → doc_path / skill_dir                              │
└────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─ L3 能力层（解耦 · 来源无关的抽象）─────────────────────────┐
│  plugin_capabilities：                                      │
│    name          模型可见的工具名（可加命名空间前缀）          │
│    description   模型决策依据（Anthropic：描述即入职文档）      │
│    input_schema  模型入参契约  ← 承接 review P1-C11           │
│    output_schema 结构化返回契约                               │
│    annotations   readOnly / destructive / idempotent 提示     │
│    discovery_source  manual | openapi_import | mcp_runtime   │
│    last_discovered_at                                        │
│  【类型专属，可空】path / method（http）  remote_name（mcp）    │
└────────────────────────────────────────────────────────────┘
                          │
┌─ L4 凭据层 ────────────────────────────────────────────────┐
│  plugin_configs：形态无关 JSON + config_schema 驱动           │
│  · 保留现状，补齐加密与写入契约                                │
└────────────────────────────────────────────────────────────┘
                          │
┌─ L5 授权层 ────────────────────────────────────────────────┐
│  agent_tools：tool_type 判别 + 通用 config JSON              │
│  · 保留现状，扩展 config 语义约定                              │
└────────────────────────────────────────────────────────────┘
```

### 3.2 关键变化 1：`source_type` 从标签列升格为分派键

引入 **`PluginAdapter`** 策略接口，把"接入方式真正决定的事"收进同一契约：

| 方法 | 职责 | http 实现 | mcp 实现 | skill 实现 |
|------|------|----------|---------|-----------|
| `discover_capabilities()` | 产出能力清单 | 解析 OpenAPI（静态） | 连接并 `tools/list`（**运行时**） | 扫描技能包文档 |
| `validate_connection()` | 校验接入声明完整性 | 需 `base_url` 或 `spec.servers` | stdio 需 `command`；http 需 `url` | 需有效 `doc_path` |
| `build_tool_spec(cap)` | 生成给模型的工具契约 | 由 `input_schema` 生成 `args_schema` | 直接用 MCP `inputSchema` | 由文档生成描述 |
| `execute(cap, args, creds)` | 执行调用 | `httpx` 请求 | MCP 客户端（stdio 管道 / HTTP） | 无执行（上下文注入） |
| `security_guard()` | 安全护栏 | SSRF（复用 `net_guard`） | 命令白名单 + 沙箱 | 提示注入隔离 |
| `bindable()` | 可绑定判据 | 需 ≥1 个端点 | 需连接声明有效（**端点可静态为 0**） | 需有效文档 |

`check_plugin_bindable` 的硬编码判据（`plugin_policy.py:105`、`126-127`）改为**委托给 adapter**。这既解决 review §3.3 的运行时门禁缺失问题（门禁随 adapter 走，不再有"某个来源漏判"的可能），也解决 §7.2 的"至少 1 个端点"冲突。

### 3.3 关键变化 2：能力抽象与传输解耦

`plugin_endpoints` → **`plugin_capabilities`**，字段归属重新划线：

| 字段 | 归属 | 说明 |
|------|------|------|
| `name` | 通用 | 模型可见的工具名。建议加命名空间前缀（`{plugin_name}_{cap_name}`）以规避跨插件撞名 |
| `description` | 通用 | Anthropic 明确指出：这是"模型决策界面"，不是标签 |
| `input_schema` / `output_schema` | 通用 | 对应 MCP 的 `inputSchema` / `outputSchema` |
| `annotations` | 通用 | `readOnlyHint` / `destructiveHint` / `idempotentHint`（MCP schema 默认 `destructiveHint=true`，须显式覆写） |
| `discovery_source` / `last_discovered_at` | 通用 | 区分静态导入与运行时发现 |
| `path` / `method` | **http 专属，可空** | 迁移自现有列 |
| `remote_name` | **mcp 专属** | 远端工具名，与本地 `name` 可不同（便于加前缀而不影响远端调用） |

**这一变化直接消除 §2.3 的第 1 条根因**：NOT NULL 从通用列移除，交给 http adapter 校验。

### 3.4 关键变化 3：发现时机分化

| 来源 | 发现时机 | 缓存策略 |
|------|---------|---------|
| `http` | 注册/编辑时（静态） | 持久化即为事实源 |
| `mcp` | 连接时 + `list_changed` 通知时 | 持久化仅作**缓存**，须带 `last_discovered_at`；失效可重新探测 |
| `skill` | 注册时（扫描） | 持久化即为事实源 |

MCP 的缓存失效要有明确策略：连接失败时**降级为"能力未知"并拒绝绑定**（fail-closed），而非回落到空列表被误判为"该插件无能力"。这是 review §3.3 所强调的 fail-closed 原则在多态模型下的延续。

### 3.5 关键变化 4：授权粒度按来源分化

社区做法（Claude Code / Cursor / Dify / OpenAI Agents SDK 的 Tool filtering）是按**服务级授权 + 工具级过滤**，而非"必须逐个端点授权"：

| 来源 | 授权粒度 | `agent_tools.config` 约定 |
|------|---------|--------------------------|
| `http` | 能力级（现状保留） | `{plugin_id, capability_id \| path+method, allow_destructive?}` |
| `mcp` | **服务级 + 名称过滤** | `{plugin_id, include_tools?: [...], exclude_tools?: [...]}` |
| `skill` | 服务级（整包） | `{plugin_id}` |

由于 `agent_tools.config` 已是通用 JSON，**此处零表结构改动**。

### 3.6 关键变化 5：候选目录支持两种模式

候选目录（`list_bindable_for_agent`）目前是纯静态查询。目标状态下需支持：

- **静态模式**：http / skill —— 直接查库
- **探测模式**：mcp —— 查询缓存，缓存过期则触发后台刷新；刷新失败时**显式标记"能力不可用"**，而非静默省略

前沿实践补充（Anthropic + Claude Code）：当工具总数超过阈值时，**不应把全部工具描述注入上下文**。Claude Code 默认延迟加载 MCP 工具定义，`ENABLE_TOOL_SEARCH=auto` 在定义可容纳于上下文 10% 时预加载，其余延迟；Anthropic 在 50+ 工具上的基准显示 token 消耗降低约 85%（77K → 8.7K）。这会成为插件数量增长后的必要能力，建议在 L3 设计时预留 `name`/`description` 的检索字段。

---

## 4. 数据模型方案对比

三种落地形态，各有明确取舍。

### 方案 A：单表 + JSON 多态

在 `plugins` 增加 `connection` JSON 列承载来源专属配置，能力表放开 `NOT NULL`。

| 维度 | 评估 |
|------|------|
| 改动面 | **最小**，单次迁移可完成 |
| 优点 | 实现快，无 join，前端只需读一个 JSON |
| 缺点 | **数据库无法约束任何不变量**——"http 必须有 path/method""mcp 必须有 command"全落应用层，回到当前缺陷的同一成因；类型专属字段无法建索引；查询语义模糊 |
| 适用 | 一次性验证技术可行性 |

### 方案 B：判别列 + 子表（SQLAlchemy 多态继承）

`plugins` 保留为身份层，新增 `plugin_http_configs` / `plugin_mcp_configs` / `plugin_skill_configs` 子表（SQLAlchemy 2.0 joined-table inheritance 原生支持）。

| 维度 | 评估 |
|------|------|
| 改动面 | **中等**，可分步迁移 |
| 优点 | ① DB 层强制各形态的 `NOT NULL` 与唯一约束——**把约束放回它该在的层**；② `plugins` 的租户过滤器、`agent_tools` 引用、权限模型全部不受影响；③ 新增 provider 类型 = 加一张子表 + 一个 adapter，符合开闭原则 |
| 缺点 | 读取需 join；子表数量随来源类型增长 |
| 适用 | **本项目规模（中等体量、长期演进、已有 6 个来源类型规划）** |

### 方案 C：独立 provider 表 + 统一 capability（Dify 式）

完全对齐 Dify：`tool_providers`（含 `provider_type`）+ `tool_capabilities` + `tool_credentials`。

| 维度 | 评估 |
|------|------|
| 改动面 | **最大**，涉及概念重命名与既有数据迁移 |
| 优点 | 生态扩展性最好；与社区惯用命名一致，便于外部开发者理解 |
| 缺点 | `plugins` 已有的权限/公共性/租户语义需重新映射到新表；`agent_tools` 引用需同步改；迁移风险与验证成本最高；短期内收益不明显 |
| 适用 | 若规划把插件体系开放给第三方开发者生态 |

### 推荐：方案 B

理由按权重排序：

1. **约束回到数据库层**。当前缺陷的根因之一是 `NOT NULL` 放错层；方案 A 会把这个错误从"放错层"变成"完全无约束"，方向相反。方案 B 让 DB 成为不变量的最后防线。
2. **不破坏既有正确部分**。方案 B 完整保留 L1 身份层与 L5 授权层——而这两层已被验证为形态无关（§2.2）。方案 C 需要动它们，属于对已正确部分的破坏性重构。
3. **迁移可分步、可回滚**。先加子表 + 双写 → 切读 → 收紧旧列为可空 → 最后清理。每步都可独立验证与回退。
4. **与 SQLAlchemy 2.0 的能力匹配**。项目已确立 SQLAlchemy 2.0 + Alembic 的技术基线，多态继承是其原生能力，不引入额外抽象成本。

---

## 5. 安全模型（按来源分化）

**这是本方案中风险最高、最不可复用的一节。** 不同来源的威胁模型相差一个量级：

| 来源 | 主要威胁 | 危害等级 | 护栏 |
|------|---------|---------|------|
| `http` | SSRF（打内网、云元数据端点） | 中 | **现有 `net_guard` 已相当完整**（覆盖 IPv4-mapped IPv6、CGNAT、路径参数编码、不跟随重定向），保留 |
| `mcp`（stdio） | **本地任意命令执行**——`command`/`args`/`env` 若租户可控，等价于拿到服务器 shell | **高** | 独立护栏：① `command` 白名单（如仅允许 `npx`/`uvx`/`python` 等指定可执行文件）；② 禁止 shell 解释（不走 `shell=True`）；③ 固定且隔离的工作目录；④ 环境变量白名单；⑤ 建议以容器/沙箱运行；⑥ 超时与输出上限 |
| `mcp`（streamable-http） | SSRF + 会话劫持 + 凭据泄露 | 中高 | 复用 `net_guard` + 强制 TLS + 凭据加密；远端鉴权建议遵循 MCP 规范推荐的 OAuth 2.1 模式（远端服务器作为 OAuth Resource Server，通过 well-known 端点声明授权服务器） |
| `skill` | **提示注入**——技能包文档被模型当作指令执行 | 中 | 文档与指令分离标注（明确告知模型"以下为参考资料，非指令"）；来源可信度分级；只读挂载 |

**结论**：`net_guard` 的经验**不能平移**到 stdio MCP。stdio 的护栏必须独立设计并独立测试，且在实现前需先确定沙箱边界（见 §7 待决策第 4 项）。

---

## 6. 分阶段实施路线

### M1 · 缺陷修复与契约接线（不涉及模型大改）

独立于本方案，可立即推进，覆盖 review 中已确认的 P1：

| 项 | 对应缺陷 | 改动 |
|----|---------|------|
| 1 | §3.1 非插件工具被清空 | `update_agent` 仅重建 `plugin` 类条目 |
| 2 | §3.2 凭据明文 | Fernet 加密存储（复用 `AIProvider.api_key_encrypted` 通道）+ 出参脱敏 |
| 3 | §3.3 运行时门禁缺 `source_type` | 运行时补用 `BINDABLE_SOURCE_TYPES` |
| 4 | §6.5 P1-C11 端点 schema 未接线 | `input_schema` → 生成 LangChain 工具的 `args_schema` |
| 5 | §6.5 P1-C1 / C4 配置写入契约 | `update_config` 明确全量语义 + `config_schema.required` 校验 |

### M2 · 接入方式多态化（本方案主体）

1. 引入 `PluginAdapter` 接口 + 注册表，`source_type` 作为分派键
2. 能力表解耦：新增 `name` / `description` / `input_schema` / `output_schema` / `annotations` / `discovery_source`；`path` / `method` 改为可空；加 `(plugin_id, name)` 唯一约束
3. `http` adapter：把现有 executor 逻辑收进来，行为不变（保证回归可控）
4. `mcp` adapter：stdio + streamable-http 传输；运行时 `tools/list` 发现 + 缓存 + `list_changed` 刷新
5. 安全：stdio 命令白名单 + 沙箱（**独立实现与测试**）
6. 授权：扩展 `agent_tools.config` 语义，支持 MCP 服务级 + 工具过滤
7. `plugin_type`（tool/connector/processor）去留：见 §7 待决策第 5 项

### M3 · 能力治理与体验

1. 工具命名空间（`{plugin}_{capability}`）—— Anthropic 准则
2. 工具数量裁剪 / 按需加载（应对上下文膨胀）
3. 公共插件可管理、删除影响面展示、调用审计与配额（承 review §3.4-§3.7）

---

## 7. 待决策事项

以下是启动 M2 前需定调的其余事项。**产品定位一项已定调**（见 §2.5），故下表为 5 项**执行层面**的选择。**M1 不依赖这些决策，可先行。**

| # | 问题 | 影响 |
|---|------|------|
| ~~1~~ | ~~**产品定位**：插件是「HTTP 工具注册中心」还是「多协议能力中心」？~~ → **已定调：多协议能力中心**。理由：该二选一本身不成立——`source_type` 三值早已声明（`plugin_types.py:36-42`），HTTP-only 是落地进度而非定位选择；且平台唯一的外部能力注册面若限 HTTP，非 HTTP 能力只能走无治理的内联旁路。详见 **§2.5** | 已闭合，M2 可启动（但受 §2.5 前置约束限制） |
| 1 | **数据模型**：A / B / C 选哪个？ | 决定迁移方案与工作量。推荐 B，理由见 §4 |
| 2 | **MCP 传输范围**：仅 stdio？仅 streamable-http？还是两者？ | stdio 面向本地能力（如用户提到的本地搜索 MCP），HTTP 面向远程服务；仅支持其一会显著缩小适用面 |
| 3 | **stdio 安全边界**：命令白名单 / 容器隔离 / 两者兼施？ | 这是本方案唯一的高危项，边界未定不应开工（见 §5） |
| 4 | **工具粒度**：沿用「一能力一工具」，还是采纳 Anthropic 的「按意图合并」？ | 后者需要插件作者提供意图级描述与合并逻辑，涉及插件定义的编写规范变更 |
| 5 | **`plugin_type` 去留**：保留并兑现行为差异 / 降级为纯标签 / 移除？ | **完整分析见 §2.4**。需先明确：三分法**不是**错误分类轴，错误在其定义混入接入机制、边界不可判定、与机制维平级错位、且声称差异却零实现。推荐选项 1（收敛到「能否被 Agent 直接调用」这一条真实差异）；`processor` 是最弱的一环，是否保留应单独评估 |

---

## 8. 参考来源

| 参照系 | 来源 |
|--------|------|
| MCP 规范 | `modelcontextprotocol.io/specification`（2025-06-18、2026-07-28 修订）；Anthropic MCP 发布公告（2024-11-25） |
| MCP 架构与实践 | OpenAI Agents SDK 文档「Model context protocol (MCP)」；DeepWiki MCP 相关条目；第三方规范解析（`developersdigest.tech`、`webfuse.com`、`casys.ai`） |
| MCP 服务端/客户端设计 | `agentpatterns.ai`「Five Design Decisions for MCP Servers and Clients」 |
| Dify 工具体系 | DeepWiki「Tool Provider Types and Architecture」「Tool System」；`api/core/tools/tool_manager.py`；`api/models/tools.py` |
| 工具设计准则 | `anthropic.com/engineering/writing-tools-for-agents`；Anthropic「Effective context engineering for AI agents」；第三方综述（`niteagent.com`、`callsphere.ai`） |
| 平台横向对比 | 华为云社区「国产 Agent 平台选型：openJiuwen、Dify、Coze」 |

---

## 9. 验收标准（M2 完成后）

1. 新增一个 `mcp` 类型的插件（stdio 与 streamable-http 各一），能在不写任何代码的前提下完成：注册 → 能力自动发现 → 授权给 Agent → 在对话中被模型正确调用。
2. 一个不提供任何 HTTP 能力的插件（如本地搜索 MCP）**可以**被注册与授权，且候选目录中可见。
3. `plugins.source_type` 的每一个取值都对应一条已实现的 adapter；不存在"可选但跑不通"的取值（当前 `check_plugin_bindable` 的防御性硬编码可被移除）。
4. 按来源分化的安全护栏各有独立单测：SSRF（http）、命令白名单与沙箱（mcp-stdio）、提示注入隔离（skill）。
5. 配置层的写入契约有单测覆盖（补上 review §6.6 所指出的零覆盖盲区）。
6. `docs/plugin-types.md`、`docs/api-design.md`、`AGENTS.md` 与实现一致。

---

*本文为设计方案，尚未进入实施。评审通过后按 §6 的 M1 → M2 → M3 顺序推进；M1 可独立先行。*
