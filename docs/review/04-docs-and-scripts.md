# 04 · 文档一致性与脚本评审

> 范围：`docs/` 文档体系、根目录 `README.md` / `AGENTS.md` / `CLAUDE.md`、以及项目脚本的可执行性

---

## 结论

项目的文档**数量充足、单篇质量不低**（`core-mechanisms.md` 38 KB、`database-design.md` 20 KB、`sse-best-practices.md` 16 KB，均达到可交付水准），但存在三个结构性问题：

1. **文档与代码发生系统性漂移**，且方向不一致 —— 有的接口文档描述了并不存在的路径，有的把已实现的能力写在错误的路径下。
2. **文档主体冻结在项目启动周**。`docs/` 下 6 份核心文档的文件时间戳均为 2026-07-21，而 git 历史显示此后完成了 UUID 主键重构与 Phase 6/7/8（工作流、插件、审计）等大量演进，**均未回写文档**。
3. **最关键的技术文档 `AGENTS.md` 未纳入版本控制**（见 [03](03-engineering.md)），导致"最新、最准确的那份文档"恰好是协作方拿不到的那份。

另有一处会直接导致执行失败的脚本缺陷（A4）。

---

## 一、D6 / D7 · 文档体系盘点与漂移证据

`docs/` 下 12 个 Markdown 文件 + 3 个子目录：

| 文件 | 大小 | 最后修改 | 已入库 | 状态评估 |
|------|------|----------|--------|----------|
| `architecture.md` | 8.8 KB | 2026-08-26 | 是 | 系统架构，唯一在启动周之后更新过的核心文档 |
| `api-design.md` | 11.8 KB | 2026-07-21 | 是 | **内容漂移最严重**（见 §2） |
| `database-design.md` | 20.4 KB | 2026-07-21 | 是 | 停留在 UUID 重构之前的设计 |
| `core-mechanisms.md` | 38.3 KB | 2026-07-21 | 是 | 篇幅最大，质量高，但同样冻结 |
| `frontend-design.md` | 14.9 KB | 2026-07-21 | 是 | 同上 |
| `implementation-plan.md` | 16.7 KB | 2026-07-21 | 是 | 分阶段计划，需标注实际完成状态 |
| `sse-best-practices.md` | 16.2 KB | 2026-07-21 | 是 | 独立的技术专题文档 |
| `phase4-knowledge-base-summary.md` | 10.1 KB | 2026-07-21 | 是 | 单阶段总结 |
| `knowledge-base-enhancement-assessment.md` | 26.3 KB | 2026-09-11 | **否** | 知识库增强评估报告 |
| `plan-knowledge-retrieval-p0-p2.md` | 20.3 KB | 2026-09-11 | **否** | **已自标废弃**（见 §4） |
| `plan-readme-refactor.md` | 3.2 KB | 2026-09-11 | **否** | README 重构计划 |
| `rag-eval/`（3 文件） | — | 2026-09-11 | **否** | `PLAN.md` v2.0、`RERANKER-DESIGN.md`、`batch1-delivery.md` —— 为当前权威计划 |
| `assets/` | — | — | **否** | 截图目录，**`README.md` 正文引用了其中的图片**（`docs/assets/screenshots/01-dashboard.png` 等） |
| `superpowers/` | — | 2026-07-21 | 是 | 用途需确认 |

**时间戳证据的含义**：`git status` 中上述 6 份核心文档**均不在 modified 列表**，说明它们的当前内容与最初提交一致。而在同期的 git 历史中可看到 `refactor: 重构数据库自增id改为uuid`、`feat(workflow)` 系列、`docs: update documentation for Phase 6 workflow engine` 等提交。结论：**代码演进了 7 周以上，主体文档未同步**。

**值得注意的特殊情况**：`README.md` 正文引用了 `docs/assets/screenshots/` 下的图片，而该目录**未入库** —— 这意味着协作者 clone 后 README 中的图片全部显示为破图。

---

## 二、D1 / D2 · 接口文档与实现漂移

### 2.1 声明了但实际不存在的接口

| 文档位置 | 声明内容 | 实际情况 |
|----------|----------|----------|
| `docs/api-design.md` §4「租户管理 `/api/tenants`」 | `GET/PUT /tenants/current`、`/tenants/current/members`、`PUT /tenants/current/members/{user_id}/role` | **无 `tenants` 路由**。租户能力实际分布在：`/system/tenant`（`api/system.py:22,31` 的 `GET/PUT`，供租户自助）与 `/admin/tenants`（`api/admin.py:32-98`，供平台管理员）。文档**未记录这两处实际入口** |
| `docs/api-design.md` §5「API密钥 `/api/api-keys`」 | `GET/POST /api-keys`、`DELETE /api-keys/{id}`、`PUT /api-keys/{id}/status` | **无任何实现**。对应 [A2](01-backend.md) 的死代码（`models/api_key.py` 与 `generate_api_key` 均无引用）。属"文档描述了完整的接口设计、代码停留在建表阶段" |

**评价**：§4 属于"能力存在但文档写错了位置"，§5 属于"完全未实现"。两者性质不同，但都会误导调用方 —— 按文档写前端代码会拿到 404。

### 2.2 路由前缀与路径漂移

后端实际注册前缀见 `backend/app/main.py:114-126`。逐条比对结果：

| 文档章节 | 文档声明前缀 | 实际前缀 | 一致 |
|----------|--------------|----------|------|
| §1 认证 | `/api/auth` | `/auth` | 一致（`/api` 为全局约定） |
| §2 用户管理 | `/api/users` | `/users` | 一致 |
| §3 角色与权限 | `/api/roles` | `/roles` | 一致 |
| §4 租户管理 | `/api/tenants` | **不存在** | 见 2.1 |
| §5 API密钥 | `/api/api-keys` | **不存在** | 见 2.1 |
| §6 AI供应商 | `/api/ai-providers` | **`/providers`**（`main.py:115`） | **不一致** |
| §7 AI模型 | `/api/ai-models` | `/ai-models` | 一致 |
| §8 Prompt管理 | `/api/prompts` | `/prompts` | 一致 |
| §9 知识库 | `/api/knowledge` | `/knowledge` | 一致（文档已自行加注说明） |
| §10 工作流 | `/api/workflows` | `/workflows` | 一致 |
| §11 Agent | `/api/agents` | **`/agent`**（`main.py:119`） | **不一致** |
| §12 插件 | `/api/plugins` | `/plugins` | 一致 |
| §13 审计与监控 | `/api/audit` | `/audit` | 一致 |
| §14 平台管理 | `/api/admin` | `/admin` | 一致 |

### 2.3 Agent 端点路径的错误（漂移最严重的一处）

`docs/api-design.md` §11 与实际实现逐条对照：

| 文档声明 | 实际实现（`api/agent.py`） | 差异 |
|----------|---------------------------|------|
| `GET /agents` | `GET /agent/agents`（`:62`） | 前缀 |
| `POST /agents/{id}/chat`（标注"SSE 流式"） | `POST /agent/agents/{agent_id}/chat`（`:283`），函数 docstring 为 **"Agent对话（阻塞式）"** | **语义标注相反** |
| `POST /agents/{id}/chat/block`（标注"阻塞模式"） | **不存在该路径**。SSE 流式实际为 `POST /agent/agents/{agent_id}/chat/stream`（`:346`） | **路径名不存在** |
| `GET /agents/{id}/conversations/{conv_id}` | `GET /agent/conversations/{conversation_id}`（`:219`） | 未按 agent 嵌套 |
| `GET /agents/{id}/conversations/{conv_id}/messages` | 未在文档中体现；实际对话消息通过 `GET /agent/conversations/{conversation_id}`（`:219`）获取 | 结构与文档不符 |

**关键点**：文档把 SSE 端点标为 `/chat`、把阻塞端点标为 `/chat/block`，**恰好与实际相反**（实际 `/chat` 是阻塞、`/chat/stream` 是 SSE），且 `/chat/block` 不存在。好在**前端实现是正确的** —— `pages/Agents/AgentChat.tsx:162` 调用的是 `/api/agent/agents/${agentId}/chat/stream`，与后端一致。因此这是**纯文档错误**，未造成功能故障，但会使任何按文档对接的第三方立即失败。

### 2.4 文档内部计数不自洽

`docs/api-design.md` §9 声明"共实现 13 个端点"，但紧随其后的表格仅列出 **11 行**；`api/knowledge.py` 实际注册路由数亦为 **11**（`:20,50,90,110,133,153,203,260,280,300,338`）。文档自身的数字与其表格、以及实际实现三者不一致。

### 改进建议

1. **以 OpenAPI 为单一事实来源**：后端已自动生成 `/openapi.json`，建议文档改为引用它，并在 CI 中用 **Spectral** 校验规范质量（如路径命名一致性、是否缺少 `operationId`）。
2. **修正 §4、§5、§6、§11**：`/ai-providers` → `/providers`；Agent 章节整体重写（前缀 `/agent`、补 `/chat/stream`、修正 `/chat` 的语义标注、补 `/conversations` 结构）；§4 补充 `/system/tenant` 与 `/admin/tenants` 的真实入口；§5 标注"未实现"或直接删除（配合 A2 删除死代码的决策）。
3. **前端类型由 OpenAPI 生成**，消除 `types/` 下手写类型与后端的漂移可能（关联 [E10](02-frontend.md)）。
4. 文档头部统一加"最后校对版本（commit hash）"字段，使漂移可被度量。

**验收标准**：`docs/api-design.md` 中每一条路径都能在 `openapi.json` 中找到对应项（可脚本化校验）；CI 中该检查为阻断项。

---

## 三、A4 · `run_server.sh` 硬编码失效路径（P2）

**位置**：`backend/run_server.sh`

```bash
#!/bin/bash
# 后端服务启动脚本

cd /Volumes/Project/qiugu/AI-Studio/backend    # ← 路径不存在
```

**问题**：脚本中的绝对路径为 `/Volumes/Project/qiugu/AI-Studio/backend`，而项目实际位于 `/Volumes/Document/qiugu/AI-Studio/backend`。**该脚本在任何机器上执行都会立即失败**（`cd` 失败后仍会继续执行后续的 `python -m uvicorn`，但工作目录错误，`app.main:app` 将无法导入）。

**影响**：虽属小问题，但它是"唯一被提交的启动脚本"—— 新人按目录结构找到它并执行，会得到语焉不详的导入错误。

**改进建议**：改为基于脚本自身位置推导路径：

```bash
cd "$(dirname "$0")"          # 或使用 git rev-parse --show-toplevel
```

**验收标准**：在任意工作目录下执行 `bash backend/run_server.sh` 均能正确定位并启动服务。

**附带观察**：`backend/` 下另有 `main.py`、`debug_retrieval_repro.py` 两个根级脚本。`debug_retrieval_repro.py` 从命名判断为临时调试脚本，建议确认其是否应保留在仓库根目录（若为一次性排查工具，宜移入 `scripts/` 或删除）。

---

## 四、D3 · 废弃文档未归档（P2）

**位置**：`docs/plan-knowledge-retrieval-p0-p2.md`（20.3 KB，未入库）

该文件开头已自标废弃：

> **本文件已废弃（历史文档）**：内容已合并至 `docs/rag-eval/PLAN.md` **v2.0**。
> 合并原因：项目中已存在同日编制、范围重叠的 `docs/rag-eval/PLAN.md`（v1.1，已通过 Q1–Q4 决策）。经评审决定合并为单一计划，统一置于 `docs/rag-eval/`。
> 本文件保留仅作历史追溯，**后续一切以 `docs/rag-eval/PLAN.md` 为准**。

**评价**：**标注废弃并指向继任文档的做法是正确且值得肯定的** —— 这远优于直接删除或留下无说明的重复文档。问题仅在于它仍位于 `docs/` 顶层，与现行文档混放，容易被检索到并被误当作有效计划。

**改进建议**：移入 `docs/archive/`（新建目录）或直接删除（内容已完整合并）。若保留，建议同时归档 `docs/plan-readme-refactor.md`（若已完成）以保持 `docs/` 顶层只含现行文档。

**验收标准**：`docs/` 顶层不再出现带有"已废弃"标记的文件。

---

## 五、D8 · `CLAUDE.md` 编码约定的遵守情况

`CLAUDE.md`（17.1 KB，已入库）与 `AGENTS.md`（11.7 KB，**未入库**）定义了明确的编码约定。逐条核对其在代码中的落地情况：

| 约定 | 要求 | 实际情况 | 判定 |
|------|------|----------|------|
| 多租户隔离 | "所有数据访问必须通过 `BaseRepository`，禁止在 Service 层裸写 `db.query(Model)`" | services 层存在 **49 处**直接 `db.query`/`execute`（`repositories/` 仅被 4 个 service 使用） | **系统性违反** → [S3](01-backend.md) |
| 异常处理 | "使用 `app/core/exceptions.py` 自定义异常，禁止直接抛 `HTTPException`" | **25 处**裸 `raise HTTPException`（`api/knowledge.py` 13、`api/agent.py` 12），且存在 `AppException → HTTPException` 的反向转换 | **系统性违反** → [C1](01-backend.md) |
| 统一响应 | `{ "code": 0, "message": "success", "data": {} }` | 成功路径合规；失败路径因上述违反返回 `{detail}`；且 `code` 语义二义 | **部分违反** → [C2](01-backend.md) |
| 权限守卫 | "路由使用 `require_permission`，超级管理员接口使用 `require_platform_admin`" | `knowledge`/`agent`/`workflow` 合规；`admin`/`role`/`user`/`system`/`audit` 合规；**`ai_provider`/`ai_model`/`prompt`/`plugin` 仅 `CurrentUser`** | **部分违反** → [S2](01-backend.md) |
| SSE 规范 | `event: message\ndata: {...}\n\n`，`ensure_ascii=False`，`media_type="text/event-stream"` | `api/agent.py:346` 与 `api/workflow.py:205` 两处实现，格式与编码均合规 | **合规**（正面） |
| 主键规范 | 核心业务 ID 为字符串 UUID v4，模型定义为 `String(36)` | 已通过 `a1b2c3d4e5f6_change_all_ids_to_uuid.py` 与 `f7a3b8c7d9e0_change_uuid_columns_to_string36.py` 两次迁移完成，模型与迁移一致 | **合规**（正面） |
| 配额检查 | "创建受限资源前先调用 `QuotaService`" | `services/ai_model.py:63` 调用了 `check_model_quota`；其他受限资源需逐一确认 | **部分合规**（未逐项验证） |

**关键观察**：`CLAUDE.md` 的约定本身是**合理且专业的**（例如"禁止裸 `HTTPException`"、"所有数据访问经 `BaseRepository`"都是恰当的架构约束）。问题不在于约定写错，而在于：

1. **没有任何自动化手段强制它们**（无 lint 规则、无 CI、无对应测试）；
2. **违反的规模（49 处、25 处）说明这已不是个别疏忽，而是团队实际遵循的模式与文档约定分叉**。

因此本报告在路线图中把"建立门禁"置于"修复具体缺陷"之前。若只修缺陷而不建门禁，约定会在下一次迭代中再次分叉。**同时必须指出：如果团队已通过实践认可「service 层手工过滤租户」是当前阶段的合理选择，那么正确的动作是修改 `CLAUDE.md` 使文档反映现实，而不是让文档继续描述一个未被执行的标准。** 二者必选其一，但不作为才是最差的选择。

---

## 六、文档与脚本问题优先级汇总

| ID | 严重度 | 问题 | 一句话理由 |
|----|--------|------|-----------|
| D2 | P1 | Agent 章节的 SSE/阻塞端点标注与实际相反，且 `/chat/block` 不存在；§6 的 `/api/ai-providers` 实际为 `/providers` | 按文档对接会立即失败；前端恰好实现正确才未暴露 |
| D1 | P1 | §4 租户接口路径错误（实际在 `/system/tenant` 与 `/admin/tenants`）、§5 API 密钥接口完全未实现；§9 声明 13 个端点而表格与实际均为 11 个 | 前者误导调用方，后者是文档化的空承诺，且文档内部不自洽 |
| D6 | P1 | 6 份核心文档冻结于 2026-07-21，此后 7 周代码演进未回写 | 文档可信度随时间单调下降 |
| D8 | P1 | `CLAUDE.md` 约定违反规模达 49 处 / 25 处 | 文档与现实分叉，需在"修代码"与"修文档"间明确决策 |
| A4 | P2 | `run_server.sh` 硬编码失效路径 | 脚本在任何机器上都会失败 |
| D3 | P2 | 废弃文档未归档至 `archive/` | 已在文件内正确标注废弃，仅需归档 |
| D7 | P2 | `README.md` 引用的 `docs/assets/` 截图目录未入库 | clone 后 README 破图 |
