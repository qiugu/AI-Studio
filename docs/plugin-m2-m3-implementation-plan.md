# 插件能力模型 M2 / M3 实施计划

> **文档性质**：实施计划 · **已终审**。承接 [plugin-capability-model-design.md](plugin-capability-model-design.md) §6 的路线图，落地 M2（接入方式多态化）与 M3（能力治理与体验）。
> **前置**：M1 已落地（见 [plugin-usage-flow-review.md](plugin-usage-flow-review.md) §8）。
> **推进要求**：按项目约定，计划经评审确认后按 M2.0 → M2.6 → M3.x 顺序推进，每完成一个子阶段即提交验证证据。
>
> **进度**
> - ✅ **M2.0 已落地（2026-09-14）**：`plugin_type` 已从数据模型 / 接口 / 前端 / 文档全链路移除，迁移 `h2i3j4k5l6m7` 已在实库执行。落地记录见 [plugin-usage-flow-review.md](plugin-usage-flow-review.md) §8.6。
> - ⬜ M2.1 起待推进。

---

## 0. 已定调决策（本轮评审确认）

| # | 决策项 | 结论 | 影响 |
|---|--------|------|------|
| 1 | 数据模型 | **方案 B**：判别列 + 子表（SQLAlchemy joined-table inheritance） | 决定 §2 表结构与 §4 迁移策略 |
| 2 | MCP 传输范围 | **stdio + streamable-http** | 决定 M2.3 适配器与 §5 stdio 沙箱 |
| 3 | stdio 安全边界 | **命令白名单 + 纵深防护**（禁 shell / 隔离 cwd / env 白名单 / 超时与输出上限） | 决定 M2.4 |
| 4 | `plugin_type` 去留 | **移除该字段** | 决定 M2.0 |
| 5 | MCP 客户端库选型 | **官方 `mcp` 2.x**（不引入 fastmcp） | 决定 M2.3 客户端封装与依赖 |

---

## 1. 范围

**在范围**：M2（接入方式多态化）+ M3（能力治理与体验）的全部内容。

**不在范围**（明确排除，避免范围蔓延）：
- 提示词/资源类原语（MCP `resources` / `prompts`）的完整实现——本期只落地 `tools`，`resources`/`prompts` 预留数据字段不接执行。
- OAuth 2.1 远端鉴权——本期 mcp(streamable-http) 仅支持静态凭据（Bearer/自定义头），OAuth 列入后续。
- 第三方插件市场与签名分发。

---

## 2. 目标数据模型（方案 B）

### 2.1 五层结构

```
L1 身份层   plugins               （保留；移除 plugin_type；api_spec 迁出）
   │
   │  source_type 作为【分派键】
   ▼
L2 接入声明层（新增，按 source_type 建子表）
   ├─ plugin_http_configs   （http 专属）
   ├─ plugin_mcp_configs    （mcp 专属）
   └─ plugin_skill_configs  （skill 专属）
   │
   ▼
L3 能力层   plugin_capabilities   （plugin_endpoints 解耦而来；path/method 改可空）
   │
L4 凭据层   plugin_configs        （保留；M1 已加密）
   │
L5 授权层   agent_tools           （保留；config JSON 扩展语义）
```

### 2.2 表结构变更

**L1 `plugins`（改）**
- 移除列：`plugin_type`
- 迁出列：`api_spec` → `plugin_http_configs.api_spec`（迁移期双写，见 §4）
- 保留：`id / tenant_id / name / source_type / version / description / config_schema / icon / author / homepage_url / status / is_public / created_at / updated_at`

**L2 接入声明层（新增三表）**

| 表 | 列 | 说明 |
|----|----|------|
| `plugin_http_configs` | `plugin_id` (PK/FK, CASCADE)、`api_spec` JSON NULL | http 专属连接声明 |
| `plugin_mcp_configs` | `plugin_id` (PK/FK)、`transport` VARCHAR(20) NOT NULL（`stdio`/`streamable_http`）、`command` VARCHAR(255) NULL、`args` JSON NULL、`url` VARCHAR(500) NULL、`headers` JSON NULL、`include_tools` JSON NULL、`exclude_tools` JSON NULL | mcp 专属；`command` 与 `url` 按 transport 二选一（应用层校验，故均可空） |
| `plugin_skill_configs` | `plugin_id` (PK/FK)、`doc_path` VARCHAR(500) NULL、`skill_dir` VARCHAR(500) NULL | skill 专属 |

> **凭据归属**：mcp(stdio) 的 `env`（含 API Key）**不放 L2**，而放 L4 `plugin_configs`（形态无关 JSON，按租户隔离）。L2 只承载「连接怎么建」，L4 承载「每个租户各自的凭据」。这是 M1 已确立的分层。

**L3 `plugin_capabilities`（由 `plugin_endpoints` 解耦而来）**

| 列 | 归属 | 说明 |
|----|------|------|
| `id` / `plugin_id` | 通用 | 主键 / 外键 |
| `name` | 通用 | 模型可见工具名（M3.1 加命名空间前缀） |
| `description` | 通用 | 面向模型的描述（Anthropic：描述即入职文档） |
| `input_schema` JSON | 通用 | 由 `request_body_schema` 升格 |
| `output_schema` JSON | 通用 | 由 `response_schema` 升格 |
| `annotations` JSON | 通用 | `readOnlyHint` / `destructiveHint` / `idempotentHint` |
| `discovery_source` VARCHAR(20) | 通用 | `manual` / `openapi_import` / `mcp_runtime` |
| `last_discovered_at` | 通用 | mcp 缓存时效判定 |
| `path` VARCHAR(500) NULL | **http 专属** | 原 `endpoint`，改可空 |
| `method` VARCHAR(10) NULL | **http 专属** | 改可空 |
| `headers` JSON NULL | **http 专属** | 端点默认头 |
| `remote_name` VARCHAR(255) NULL | **mcp 专属** | 远端工具名（本地 `name` 可加前缀而不影响远端调用） |
| `is_enabled` | 通用 | 新增，便于禁用单个能力 |

- 约束：`UNIQUE(plugin_id, name)`（原 `plugin_endpoints` 无唯一约束，见 review P2-C7）
- 保留列 `endpoint` 作为过渡视图列，迁移完成后重命名为 `path`

**L4 / L5**：`plugin_configs`、`agent_tools` **零表结构改动**（仅扩展 `agent_tools.config` 的语义约定，见 M2.5）。

---

## 3. 子阶段与改动清单

### M2.0 · 移除 `plugin_type`（决策 4）

| 层 | 文件 | 改动 |
|----|------|------|
| 后端 | `core/plugin_types.py` | 移除 `PluginType` 枚举与 `PLUGIN_TYPE_META` |
| 后端 | `models/plugin.py` | 移除 `plugin_type` 列 |
| 后端 | `schemas/plugin.py` | 移除 create/update/out 的 `plugin_type` 字段 |
| 后端 | `services/plugin.py` | 移除按 `plugin_type` 的过滤与排序参数 |
| 后端 | `api/plugin.py`、`api/agent.py` | 移除 `plugin_type` 入参与候选目录回显 |
| 前端 | `types/plugin.ts`、`pages/Plugins/pluginMeta.ts`、`PluginList.tsx`、`PluginForm.tsx`、`PluginConfig.tsx`、Agent 绑定 UI | 移除类型展示/筛选/表单字段 |
| 迁移 | 见 §4 Step A | `DROP COLUMN plugins.plugin_type` |

**验收**：全仓 `grep -rn "plugin_type"` 无残留（文档与迁移除外）；插件列表/表单/绑定 UI 无类型入口；既有数据不受影响。

### M2.1 · 数据模型与迁移（决策 1）

新增 §2.2 的三张接入声明子表与 `plugin_capabilities`；`plugin_endpoints` 数据回填至 `plugin_capabilities`（`endpoint→path`、`method→method`、`request_body_schema→input_schema`、`response_schema→output_schema`、`discovery_source=openapi_import`）；`plugins.api_spec` 回填至 `plugin_http_configs`。

**改动文件**：`models/plugin.py`、`alembic/versions/<新>.py`（迁移，见 §4）。

**验收**：`alembic upgrade head` 在实库通过；`information_schema` 确认新表/新列；回填行数与源表一致；`alembic downgrade -1` 可回退且不丢数据。

### M2.2 · Adapter 接口与注册表（决策 1）

新增 `PluginAdapter` 策略接口与按 `source_type` 分派的注册表；把 `core/plugin_policy.py` 的硬编码判据委托给 adapter；`http` adapter 包装现有 `plugin_executor`，**行为不变**。

| 新增/改动 | 文件 | 说明 |
|-----------|------|------|
| ABC | `core/plugin_adapters/base.py` | `discover_capabilities / validate_connection / build_tool_spec / execute / security_guard / bindable` 六方法 |
| 注册表 | `core/plugin_adapters/registry.py` | `get_adapter(source_type) -> PluginAdapter`（未知来源返回 `None` → fail-closed） |
| http 实现 | `core/plugin_adapters/http.py` | 包装 `utils/plugin_executor.execute_plugin_call`；`security_guard` 复用 `net_guard` |
| 占位 | `core/plugin_adapters/mcp.py`、`skill.py` | M2.3 / M3 前返回明确的「未实现」 |
| 判据委托 | `core/plugin_policy.py` | `check_plugin_bindable` / `check_plugin_source_gate` 改为委托 `adapter.bindable()` / 注册表存在性 |
| 运行时接线 | `services/agent.py:_build_langchain_tools` plugin 分支 | 改为 `adapter.build_tool_spec` → 构造 Tool；`execute` 走 adapter |
| 设计期接线 | `services/plugin.py:list_bindable_for_agent` | 候选裁剪委托 adapter |

**验收（回归）**：现有 `test_plugin_governance.py` + `test_plugin_m1_fixes.py` 全绿；http 插件「注册→绑定→对话调用」端到端行为与改造前逐项一致。

### M2.3 · mcp adapter（决策 2）

> **勘误（2026-09-14，评审中修订）**：本节初稿按 `mcp` SDK **v1** 客户端 API 描述（`ClientSession` + `stdio_client` + `streamablehttp_client` + 显式 `initialize()`）。经核对官方文档，**`mcp` 2.x 已将其合并为单一 `Client`**（`from mcp import Client, StdioServerParameters`）；`ClientSession` 不再是主要入口，`create_connected_server_and_client_session` 已移除。以下按 **v2** 修订。

**依赖新增**：`requirements.txt` 增 `mcp>=2.2,<3.0`（官方 Python SDK；在 `backend/.venv` 以 pip 安装，非 npm）。

**库选型（决策 5）：采用官方 `mcp` 2.x，不引入 fastmcp。** 依据：

1. **fastmcp 建在官方 SDK 之上**：`fastmcp 4.0.3` → `fastmcp-slim[client]` → `mcp>=2.0,<3.0`。改用 fastmcp 并非绕开官方 SDK，而是「官方 SDK + 一层封装」，协议层同源。
2. **fastmcp 的差异化能力在服务端**：server 组合（`mount` / `import_server`）、代理（`as_proxy`）、OpenAPI / FastAPI 转 tools、Provider 架构。我们是 MCP 消费方，不发布 MCP 服务，这些能力用不上。
3. **v2 官方 SDK 已具备原属 fastmcp 的客户端便利性**：统一 `Client`、内存测试（`Client(MCPServer(...))`），以及 **stdio 子进程环境变量允许列表**（POSIX 仅透传 `HOME/LOGNAME/PATH/SHELL/TERM/USER`，显式 `env=` 合并其上）——后者直接支撑 M2.4 的 env 白名单。
4. **依赖面更小**：fastmcp 客户端额外引入 `authlib` / `rich` / `opentelemetry` / `pydantic-settings` / `platformdirs` / `python-dotenv` 等约 10 个包；多租户平台从镜像体积与 CVE 收敛角度应取小。

**v2 客户端 API 契约（M2.3 实现基准）**

```python
from mcp import Client, StdioServerParameters
from mcp.server import MCPServer          # 服务端类（原 FastMCP 更名），仅单测构造内存服务用

# stdio：进入上下文即启动子进程，退出即关停（自动收尾）
server = StdioServerParameters(
    command="npx", args=["-y", "<pkg>"],
    env={"API_KEY": "<tenant-scoped>"},   # 合并到 SDK 的最小 env 允许列表之上
)
async with Client(server) as client:
    tools = await client.list_tools()

# streamable-http
async with Client("https://host/mcp", headers={"Authorization": "Bearer <tenant-scoped>"}) as client:
    ...

# 内存测试：无子进程、无网络
async with Client(MCPServer("test")) as client:
    ...
```

- 错误类 `McpError` → `MCPError`（`from mcp.shared.exceptions import MCPError`）；超时改用**浮点秒**，超时码 `-32001 (REQUEST_TIMEOUT)`（v1 为 `timedelta` + HTTP 408）。
- `list_tools()` 分页改用 `params=PaginatedRequestParams(cursor=...)`。
- 子进程 stderr 默认透传到父进程；需重定向时用 `Client(stdio_client(server, errlog=<file>))`。

**新增传递依赖（`requirements.txt` 现无）**：`mcp-types==2.2.0`、`httpx2>=2.5`、`jsonschema>=4.20`、`opentelemetry-api>=1.28`；其余（`pydantic` / `starlette` / `sse-starlette` / `uvicorn` / `PyJWT[crypto]` / `python-multipart` / `anyio` / `typing-inspection`）现有版本已满足。**注意**：现有 `httpx==0.28.1` 与 `httpx2` 是两个不同的包，安装后须确认并存无冲突。

| 新增/改动 | 文件 | 说明 |
|-----------|------|------|
| MCP 客户端 | `utils/mcp_client.py` | 基于官方 `mcp` 2.x 的 `Client`：`stdio` 用 `StdioServerParameters(command/args/env)`，`streamable_http` 用 `Client(url, headers=...)`；上下文退出即关停子进程，无需手工清理 |
| mcp adapter | `core/plugin_adapters/mcp.py` | `discover_capabilities` = `tools/list`；`build_tool_spec` 用 MCP `inputSchema`；`execute` = `tools/call` |
| 发现与缓存 | `services/plugin.py` | 能力落 `plugin_capabilities`（`discovery_source=mcp_runtime`，带 `last_discovered_at`）；缓存过期触发刷新 |
| fail-closed | 同上 | 连接失败 → 标记「能力不可用」并**拒绝绑定**，而非回落空列表 |

**验收**：新增一个 stdio MCP 插件与一个 streamable-http MCP 插件，均能**不写代码**完成：注册 → 自动发现能力 → 授权给 Agent → 对话中被正确调用（设计 §9 第 1 条）。

### M2.4 · stdio 沙箱（决策 3，唯一高危项）

**独立模块 + 独立单测**，不复用 `net_guard`。

| 护栏 | 实现 |
|------|------|
| 命令白名单 | `utils/mcp_sandbox.py` 维护可执行文件白名单（默认 `npx` / `uvx` / `python` / `node`，可配置） |
| 禁 shell 解释 | `subprocess` 一律 `shell=False`，参数以数组传递 |
| 隔离工作目录 | 每次执行为插件创建固定且隔离的 cwd（工作区内），不落在系统临时目录。**实现前待验证**：官方 `StdioServerParameters` 文档示例只列 `command/args/env`，须用 `inspect.signature` 实测是否支持 `cwd`；若不支持，则改用 `stdio_client(...)` 自建 transport 或在命令包装层处理 |
| env 白名单 | 仅透传白名单内的环境变量 + 租户凭据，剥离其余进程环境 |
| 超时与输出上限 | 连接/调用超时；stdout/stderr 截断上限，防止内存耗尽 |

**验收（独立单测）**：非白名单命令被拒；含 shell 元字符的参数不被解释；非白名单 env 不透传；超时与输出上限生效（设计 §9 第 4 条）。

### M2.5 · 授权语义扩展

`agent_tools.config` 语义按来源分化（**零表结构改动**）：

| 来源 | config 约定 |
|------|-------------|
| http | `{plugin_id, capability_id \| endpoint_id \| path+method, allow_destructive?}` |
| mcp | `{plugin_id, include_tools?: [...], exclude_tools?: [...]}`（服务级 + 名称过滤） |
| skill | `{plugin_id}`（整包） |

**改动文件**：`core/plugin_policy.py`（判据按来源分化）、`services/agent.py`、`schemas/agent.py`；前端 Agent 绑定 UI 增加「MCP 服务级选择 + 工具过滤」。

### M2.6 · 候选目录多模式

`services/plugin.py:list_bindable_for_agent` 支持静态模式（http/skill，查库）与探测模式（mcp，查缓存 + 过期刷新 + 显式「能力不可用」标注），避免静默省略。

### M3.1 · 工具命名空间
`{plugin_name}_{capability_name}`；跨插件撞名规避；`config` 中保留映射以便回显。

### M3.2 · 工具数量裁剪 / 按需加载
当工具总数超阈值时，不把全部描述注入上下文；延迟加载 + 搜索（对齐 Claude Code `ENABLE_TOOL_SEARCH` / Anthropic 基准）。

### M3.3 · 治理与体验
公共插件可管理（启停/编辑，`isPlatformAdmin` 判定）、删除插件的影响面展示、调用审计与配额（承 review §3.4–§3.7）。

---

## 4. 迁移与回滚策略（方案 B 的可分步落地）

| Step | 动作 | 可独立回退 |
|------|------|-----------|
| A | 新增三张 L2 子表与 `plugin_capabilities`；`DROP COLUMN plugins.plugin_type`（M2.0）；`plugins.api_spec` 暂**保留** | 是（drop 新表 / 重建列） |
| B | 回填：`plugin_endpoints` → `plugin_capabilities`；`plugins.api_spec` → `plugin_http_configs`（**双写开始**） | 是 |
| C | 切读：运行时代码改读 `plugin_capabilities` / 子表 | 是（若双写未停） |
| D | 收紧：`plugin_endpoints`、`plugins.api_spec` 停写；保留兼容窗口 | 是 |
| E | 清理：drop `plugin_endpoints`、`plugins.api_spec` | 是（drop 前已有备份） |

- 每个 Step 一次迁移，**每步均验证 `upgrade`/`downgrade` 双向往返**。
- 回滚前先对相关表做整表备份（工作区内导出，避免系统临时目录）。

---

## 5. 测试计划

| 层 | 用例 | 覆盖 |
|----|------|------|
| 迁移 | `upgrade` → `information_schema` 校验 → `downgrade` → 再 `upgrade` | 新表/新列/回填行数 |
| Adapter | 注册表分派（http/mcp/skill/未知）；未知来源 fail-closed | M2.2 |
| http 回归 | 现有 `test_plugin_governance.py` + `test_plugin_m1_fixes.py` | 行为不变 |
| mcp | 官方 v2 **内存客户端**（`Client(MCPServer(...))`，无子进程/无网络）：`tools/list` 解析、`tools/call`、缓存失效、连不上 fail-closed | M2.3 |
| sandbox | 非白名单命令拒绝、shell 元字符、env 白名单、超时/输出上限 | M2.4（独立） |
| 授权 | config 三种形态的分派与门禁 | M2.5 |
| 前端 | `tsc --noEmit` + vitest | 类型与组件 |

**约束**：集成测试用内存 SQLite（`Base.metadata.create_all`）+ monkeypatch 凭据，不依赖真实 MySQL/Redis/Qdrant；SSRF/沙箱用例只用字面量与本地 mock，不发真实网络请求。

---

## 6. 验收标准（承设计文档 §9）

1. 新增 `mcp` 插件（stdio 与 streamable-http 各一），不写代码完成：注册 → 能力自动发现 → 授权 → 对话中正确调用。
2. 不提供任何 HTTP 能力的插件（本地搜索 MCP）可注册、可授权、候选目录可见。
3. `source_type` 每个取值都有已实现 adapter；无「可选但跑不通」的取值。
4. 按来源分化的安全护栏各有独立单测：SSRF（http）、命令白名单与沙箱（mcp-stdio）、提示注入隔离（skill）。
5. 配置层写入契约有单测覆盖（补 review §6.6 零覆盖盲区，M1 已部分补齐）。
6. `docs/plugin-types.md`、`docs/api-design.md`、`AGENTS.md` 与实现一致。
7. `plugin_type` 全仓无残留。

---

## 7. 风险与缓解

| 风险 | 等级 | 缓解 |
|------|------|------|
| stdio 本地任意命令执行 | **高** | M2.4 独立沙箱先于 M2.3 主体落地（决策 3 已定边界）；独立单测 |
| 数据迁移不可逆 | 中 | §4 分步 + 双写 + 每步双向验证 + 迁移前备份 |
| `api_spec` 迁出影响 executor/导入链路 | 中 | M2.2 http adapter 包装现有 executor，行为不变；回归用例锁定 |
| 新增 `mcp` SDK 及其传递依赖（`httpx2` / `jsonschema` / `opentelemetry-api` / `mcp-types`） | 低 | 在 venv 独立安装；`requirements.txt` 固定版本；安装后跑全量回归，确认与既有 `httpx==0.28.1` 并存无冲突 |
| 范围过大导致一次交付质量下降 | 中 | 按子阶段交付，每阶段独立验证与文档 |

---

## 8. 交付物

- **代码**：后端（`core/plugin_adapters/*`、`core/plugin_policy.py`、`models/plugin.py`、`services/*`、`utils/mcp_client.py`、`utils/mcp_sandbox.py`、`alembic/*`、`tests/*`）+ 前端（`types/plugin.ts`、`pages/Plugins/*`、Agent 绑定 UI）。
- **文档**：本计划；同步更新 `plugin-types.md`、`api-design.md`、`AGENTS.md`、`plugin-usage-flow-review.md`（§8 追加 M2/M3 实施记录）。
- **迁移**：按 §4 的 Step A–E 逐次落地，附实库验证证据。

---

*本计划待评审确认后进入编码。如某一子阶段需调整顺序或范围，以评审结论为准。*
