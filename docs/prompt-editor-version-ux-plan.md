# Prompt 编辑器版本化 UX 改造 — 实施计划（方案 A）

> 范围：前端 `PromptEditor` 显式化版本行为。后端、类型定义、Detail/List 页不在本次范围。
> 目标：使"编辑 Prompt"的版本语义与后端契约一致，且保留"同时改元数据+内容都能落库"的约束。

---

## 1. 背景与目标

后端已将 `PUT /{prompt_id}` 改为**仅更新元数据**（name/description/category/tags/status），内容（content）的变更必须通过 `POST /{prompt_id}/versions`（建版本，`is_current=False`）+ 可选 `activate` 完成。版本不可变，改内容 = 新建版本。

现状（已确认）：
- `frontend/src/pages/Prompts/PromptEditor.tsx:70-88` 的单点"保存"按钮隐式执行：① `updatePrompt`（元数据，无条件）→ ② `content` 变化则 `createVersion` + 强制 `activateVersion`。
- 问题：用户无从感知"改内容=建版本"；无法选择"只存草稿版、暂不激活"；后端支持的"暂存→评审→激活"流程前端走不通。

**目标（方案 A，最小必要）**：
1. 编辑器顶部展示版本上下文（当前 vN）。
2. content 变化时明确提示"将生成新版本"。
3. 保存时由用户显式选择：默认「保存并激活新版本」/「仅存为新版本（暂不激活）」。
4. content 未变时只走元数据更新，不建版本。

**硬约束（不可破坏）**：同一编辑动作中，元数据**始终保存**；内容若变化则**生成新版本**，是否激活由用户显式选择。

---

## 2. 范围

### In Scope
- `frontend/src/pages/Prompts/PromptEditor.tsx`：新增版本上下文展示、保存方式选择、调整保存逻辑。
- 新增 `frontend/src/pages/Prompts/promptSave.ts`：纯逻辑/编排模块（可单测）。
- 新增 `frontend/src/pages/Prompts/promptSave.test.ts`：单元测试用例。
- 新增测试基础设施：`vitest` devDependency + `vitest.config.ts`（复用 Vite 的 `@` 别名解析）。

### Out of Scope（属方案 B，本次不做）
- Detail 页增强（基于某版本新建 / 版本备注 / diff）。
- 后端 `PromptVersion.notes` 字段 + 迁移。
- 前端类型 `created_by: number → string` 修正（当前 UI 未使用，无运行时影响）。

---

## 3. 现状关键代码（引用）

`PromptEditor.tsx:62-94` `handleSubmit`：
```ts
if (!isEdit) {
  const res = await createPrompt({ ...values, content })   // 新建：v1 自动激活
  ...
} else {
  await updatePrompt(id, { name, description, category, tags, status }) // ① 元数据始终保存
  if (prompt?.current_version?.content !== content) {
    const vRes = await createVersion(id, { content })                    // ② 内容变化→建版本
    await activateVersion(id, vRes.data!.id)                             // ③ 强制激活
    message.success('已保存元数据并创建新版本（已激活）')
  } else {
    message.success('Prompt 更新成功')
  }
}
```
结论：当前**不会丢元数据**（`updatePrompt` 无条件先调用）。改造重点是去掉"强制激活"、改为用户可选，并让版本语义可见。

---

## 4. 设计

### 4.1 新增模块 `promptSave.ts`（纯逻辑，可单测）

```ts
// 保存模式：激活 / 仅草稿
export type SaveMode = 'activate' | 'draft'

export interface PromptSaveDeps {
  updatePrompt: (id: string, d: PromptUpdateRequest) => Promise<{ data: Prompt }>
  createVersion: (id: string, d: PromptVersionCreateRequest) => Promise<{ data: PromptVersion }>
  activateVersion: (id: string, vid: string) => Promise<{ data: PromptVersion }>
}

export async function executePromptSave(opts: {
  promptId: string
  isEdit: boolean
  contentChanged: boolean
  saveMode: SaveMode
  metadata: PromptUpdateRequest
  content: string
  deps: PromptSaveDeps
}): Promise<{ message: string; version?: PromptVersion }>
```

行为约定（即硬约束的实现）：
- `isEdit === false`：返回 `{ skip: true }`，交由组件走 `createPrompt`（保持现状，v1 自动激活）。
- `isEdit === true`：
  1. **始终** `await deps.updatePrompt(promptId, metadata)`（元数据落库）。
  2. 若 `contentChanged`：
     - `const v = await deps.createVersion(promptId, { content })`
     - 当 `saveMode === 'activate'`：`await deps.activateVersion(promptId, v.id)` → message `已创建并激活新版本 v{v.version_number}`
     - 当 `saveMode === 'draft'`：**不激活** → message `已创建新版本 v{v.version_number}（未激活）`
  3. 若 `!contentChanged`：message `Prompt 更新成功`（不建版本）。
- 健壮性：`createVersion` 成功但 `activateVersion` 抛错时，**捕获并提示** `版本已创建但未激活，请在详情页激活`，不向上抛出（避免元数据/版本已落库却被误判失败）。

> 说明：将编排逻辑从组件中抽出，既满足可测试性，也保证"元数据始终保存 + 内容可选激活"这一约束集中在单一可验证函数中。

### 4.2 编辑器 `PromptEditor.tsx` 改动

1. **版本上下文（仅 edit 模式）**，顶部标题区下方：
   - 显示 `当前版本：v{prompt.current_version?.version_number ?? '-'}`。
   - 当 `contentChanged`（即 `prompt?.current_version?.content !== content`）为真：展示 `Alert`/`Typography` 提示「内容已修改，保存时将生成新版本」。

2. **保存方式选择（仅 edit 模式 + contentChanged 时可用）**：
   - `const [saveMode, setSaveMode] = useState<SaveMode>('activate')`
   - 控件：`Radio.Group` 或 `Segmented`，两项：
     - `activate`（默认）：保存并激活新版本
     - `draft`：仅保存为新版本（暂不激活）
   - `!contentChanged` 时禁用该控件并附说明「未修改内容，仅更新元数据」。

3. **保存逻辑**：`handleSubmit` 改为调用 `executePromptSave`（注入 `updatePrompt/createVersion/activateVersion` 与 `contentChanged/saveMode`），根据返回 `message` 调用 `message.success`，最后 `navigate(`/prompts/${id}`)`.
   - 新建（`!isEdit`）路径保持 `createPrompt` 不变。

4. **文案/可访问性**：主按钮保留「保存」；辅助说明文字点出版本行为，降低用户认知负担。

---

## 5. 测试策略

### 5.1 新增测试基础设施
- `npm install -D vitest`（复用现有 Vite + `@` 别名；`vitest.config.ts` 设 `test.environment = 'node'`，仅需逻辑测试，无需 jsdom）。
- 若离线导致安装失败：降级为"纯逻辑手动验证矩阵"（见 §7），并保留 `promptSave.ts` 以便后续补测。

### 5.2 用例 `promptSave.test.ts`（mock `deps`）
| 用例 | 输入 | 期望 |
|------|------|------|
| 仅改元数据 | `isEdit=true, contentChanged=false` | 仅 `updatePrompt`；无 `createVersion`/`activateVersion`；msg=更新成功 |
| 改内容+激活 | `isEdit=true, contentChanged=true, saveMode=activate` | `updatePrompt`+`createVersion`+`activateVersion`；msg 含"已激活" |
| 改内容+草稿 | `isEdit=true, contentChanged=true, saveMode=draft` | `updatePrompt`+`createVersion`；**无** `activateVersion`；msg 含"未激活" |
| 激活失败容错 | `createVersion` 成功、`activateVersion` 抛错 | 捕获；返回 msg「版本已创建但未激活」；**不抛异常** |
| 新建不进此路径 | `isEdit=false` | 返回 `skip`，组件走 `createPrompt` |

---

## 6. 验收标准
1. 编辑页顶部显示当前版本号；content 变更时有明确提示。
2. 只改元数据的保存：不产生新版本，元数据正确更新。
3. 改内容 + 「保存并激活」：生成新版本且立即成为当前版本（Detail 页"当前"标记迁移到新版本）。
4. 改内容 + 「仅存为新版本」：生成新版本但**不**成为当前版本，可在 Detail 页手动激活。
5. 上述任一路径元数据均正确保存。
6. `npm run lint` 通过；`promptSave.test.ts` 全绿。

---

## 7. 手动验证矩阵（安装 vitest 失败时的兜底）
在浏览器按以下顺序手测，记录结果：
- 编辑元数据（不动 content）→ 保存 → Detail 页版本号不变、元数据显示新值。
- 编辑 content → 选"保存并激活" → Detail 页新版本为当前。
- 编辑 content → 选"仅存为新版本" → Detail 页新版本非当前，可手动激活。

---

## 8. 实施步骤清单
1. 安装 `vitest`，新增 `vitest.config.ts`（复用 `@` 别名）。
2. 新建 `promptSave.ts`（类型 + `executePromptSave`）。
3. 重构 `PromptEditor.tsx`：版本上下文 + 保存方式控件 + 调用 `executePromptSave`。
4. 新建 `promptSave.test.ts` 并运行单测。
5. 运行 `npm run lint`。
6. 代码审查（可读性/注释、性能与安全、风格一致性）。
7. 交付：代码 + 本计划文档（置于 `docs/`）。

---

## 9. 执行记录补遗：保存 500 的根因排查（后端，非前端）

> ⚠️ **更正**：本节初版将根因归结为"服务层漏赋 `tenant_id`"——该判断**不完整**，仅补 `tenant_id`
> 后仍 500。真正的根因见 §11（schema 与模型的 ID 类型不匹配）。此处保留排查脉络以免重蹈覆辙。

### 现象
编辑 Prompt 点击保存后，调用 `POST /{prompt_id}/versions`（建版本）接口**返回 HTTP 500**。
初判"前端把整个 prompt 参数传给了建版本接口"——**经核查不成立**：前端 `executePromptSave` 仅
`createVersion(promptId, { content })`，且后端 `PromptVersionCreate` 仅声明 `content` 字段
（Pydantic 默认忽略多余字段），不会因"多传字段"报错。

### 第一轮排查（已被证伪/不充分）
迁移 `b3c4d5e6f7a8` 把 `prompt_versions.tenant_id` 设为 NOT NULL，而服务层构造 `PromptVersion`
时未赋值 `tenant_id`。已补 `tenant_id=self.tenant_id`（`create()` / `create_version()`）。
`backend/tests/test_prompt_version_tenant.py` 2/2 通过。
**但**：仅补 `tenant_id` 不够——见 §11。

### 关键认知纠偏
前端"仍然调用保存版本接口"是**预期行为，不是 bug**：内容变更在后端设计上必然 = 新建版本
（版本不可变）。问题不在"调用了哪个接口"，而在"该接口往数据库写入时的列类型不匹配"。

---

## 10. 验证状态（历史记录，部分已过时）
- 前端单测：`npm run test` → 5/5 通过（方案 A UX 改造，仍有效）。
- 后端单测：`backend/tests/test_prompt_version_tenant.py` → 2/2 通过（仅验证 tenant_id 已赋值）。
- ⚠️ 上述后端测试使用 MagicMock，**未触及真实数据库**，因此未能暴露 §11 的真实根因。

---

## 11. 真正根因（已定位并修复）：prompt 表 schema 与模型 ID 类型不匹配

### 根因
- **模型**（`Prompt` / `PromptVersion`）：所有 `id` / `tenant_id` / 外键（`prompt_id` /
  `created_by`）均声明为 **`String(36)` UUID**。
- **建表迁移** `93a1c4f6255f_phase3_add_prompt_tables`：将上述列建成 **`BigInteger`**
  （自增整数）。
- 项目另有迁移 `f7a3b8c7d9e0_change_uuid_columns_to_string36`，意图把全库主键/外键改为
  `VARCHAR(36)`（其 `COLUMNS_BY_TABLE` 已含 prompts / prompt_versions），但**迁移历史是分叉的多
  head 链**，`f7a3b8c7d9e0` 与 prompt 表所在链不相交 → 该转换未落到 prompt 表上。
- 结果：`create_version` 往 `prompt_versions.id` / `prompt_id` / `created_by` 写入 **UUID 字符串**
  到 **`BigInteger` 列** → MySQL 严格模式 `Incorrect integer value` → **500**。
- 上一轮仅补 `tenant_id`（它本就已是 `String(36)`），未触碰其余 3 个错配列，故 500 依旧。

### 修复
新增幂等迁移 `backend/alembic/versions/d1e2f3a4b5c6_convert_prompt_tables_to_uuid.py`：
将 `prompts` / `prompt_versions` / `prompt_test_logs` 的 id/外键列统一改为 `VARCHAR(36)`。
- 复用 `f7a3b8c7d9e0` 的"先卸外键 → 改类型（已是 String 则跳过）→ 重建外键"模式；
- **幂等**：若列已是 `String` 则 no-op，重复执行安全；若已是 String(36) 则整段为空操作；
- 仅 MySQL 才执行 `SET foreign_key_checks`，避免误伤 SQLite 测试；
- `down_revision = 'b3c4d5e6f7a8'`（接在 prompt 分支链上）。

这与此前 `tenant_id` 补丁正交且互补：前者修"漏赋值"，本迁移修"类型根本错配"。

### 新增回归测试（真实执行，非 mock）
- `backend/tests/test_prompt_tables_uuid_migration.py`：在 SQLite 上构造"坏状态"库
  （prompt 三表为 BigInteger 外键），单独执行该迁移 → 断言列变 `VARCHAR(36)`、重复执行幂等、
  可回滚。**1 passed**。
- `backend/tests/test_prompt_version_service_integration.py`：桩掉重型工具模块后，在"修正后的
  String(36) schema"上**真实调用** `PromptService.create_version` → 断言成功生成 v2。**1 passed**。
- 连同 `test_prompt_version_tenant.py`，`tests/` 下 prompt 相关 **4/4 通过**。

### 应用方式（重要）
迁移历史存在多 head，请勿直接 `alembic upgrade head`（会报 multiple heads）。请按具体修订升级：
```bash
alembic upgrade d1e2f3a4b5c6
```
应用前可用以下 SQL 确认当前真实列类型（本机 MySQL 凭据未对外暴露，需自行连接）：
```sql
SHOW COLUMNS FROM prompt_versions;   -- 看 id / prompt_id / created_by 的 Type 是否为 bigint
SHOW COLUMNS FROM prompts;           -- 看 id / tenant_id / created_by 的 Type
```
若已是 `varchar(36)`，本迁移为 no-op，不影响。

### 代码审查（迁移 + 测试）
- 可读性/注释：根因、修复意图、幂等语义均在文件头与 §9–§11 写明；helper 与既有迁移同构。
- 性能/安全：外键仅在事务内临时关闭、且 SQLite 跳过；批量 `batch_alter_table` 为标准做法；
  类型检查保证对"已修正库"为 no-op，不误改、不残留中间态。
- 风格：沿用项目既有迁移模式与命名，无新增分支逻辑。

---

## 12. 执行补遗二：应用迁移时报 MySQL 1060 的修复 + 前端保存语义简化

### 12.1 现象
执行 `alembic upgrade d1e2f3a4b5c6` 时报错：
`pymysql.err.OperationalError (1060, "Duplicate column name 'tenant_id'")`，
SQL 为 `ALTER TABLE prompt_versions ADD COLUMN tenant_id VARCHAR(36)`。

### 12.2 根因
报错的 ADD COLUMN 来自**旧迁移 `b3c4d5e6f7a8`**（非新迁移 `d1e2f3a4b5c6`）。真实库的
`prompt_versions.tenant_id` 列**早已存在**，但 `alembic_version` 表未将其标记为已执行
（schema 与迁移进度不同步）。`upgrade d1e2f3a4b5c6` 会重放链条上所有未记录的迁移，
重放到 `b3c4d5e6f7a8` 的 `ADD COLUMN` 时撞上已存在的列 → 1060。

### 12.3 修复：将 `b3c4d5e6f7a8` 改为幂等迁移
每一步先经 inspector 检查真实结构：
1. 列不存在 → 才 `ADD COLUMN`（避免 1060）；
2. 列存在但类型非 String → 改为 `VARCHAR(36)`（用 `batch_alter_table`，跨方言安全）；
3. 回填改用关联子查询（`UPDATE ... SET tenant_id = (SELECT ...)`），替代 MySQL 专用的
   `UPDATE ... JOIN`，SQLite/MySQL 均可执行；
4. 仍可为空 → 才收紧 NOT NULL（已 NOT NULL 则 no-op）。

这样无论 schema 与迁移进度是否同步、重复执行多少次，`alembic upgrade d1e2f3a4b5c6` 均可安全完成。

### 12.4 验证
- 新增 `backend/tests/test_prompt_tenant_column_migration.py`：
  - 列缺失态 → 执行后新增、回填（值取自父表 prompts）、NOT NULL 收紧均正确；
  - **列已存在态（即用户的 1060 故障态）→ 重放不报错、数据不破坏（幂等）**；
  - downgrade 正确删列。
- prompt 相关后端测试合计 **7/7 通过**。

### 12.5 前端保存语义简化（应用户要求）
移除「保存方式：保存并激活 / 仅存为新版本」的选择控件——用户视角只有一个语义：
**点「保存」= 全部保存**。
- `PromptEditor.tsx`：删除 Radio 分组与 `saveMode` 状态；仅保留「当前版本 vN」展示与
  "内容已修改，保存后将自动生成新版本"的提示。
- `promptSave.ts`：删除 `SaveMode`；内容变化时固定 createVersion + activateVersion；
  消息统一为「保存成功」/「保存成功，已生成新版本 vN」。
- `promptSave.test.ts` 同步精简为 4 个用例（4/4 通过）。
- 内部仍分两步调用（updatePrompt + createVersion），这是后端数据模型决定的
  （prompts 表不存内容），但对用户不可见。

---

## 13. 执行补遗三：保存仍报 1062（版本号唯一键冲突）的根因与修复

### 13.1 现象
保存 Prompt 时报：
`pymysql.err.IntegrityError (1062, "Duplicate entry '1-1' for key 'prompt_versions.uq_prompt_version'")`，
INSERT 的 `version_number=1`，但该 prompt 已存在 ('1', 1) 的 v1。

### 13.2 根因：S3 全局租户过滤器污染了版本号计算
`app/core/tenant_scope.py`（S3 机制化兜底）通过 `with_loader_criteria` 给**所有含
`tenant_id` 列的 ORM 实体 SELECT** 自动注入 `tenant_id == 当前租户`。矛盾链：
1. `create_version` 用 ORM 查询"最大版本号"（`db.query(PromptVersion).filter(prompt_id==...)`）；
2. 该查询被注入 `AND tenant_id = '1'`，而存量 v1 行的 `tenant_id` 与当前租户不一致
   （迁移回填未覆盖的旧数据）→ 查询"看不到" v1 → `next_num` 误算为 **1**；
3. INSERT ('1', 1) 撞上已存在的 ('1', 1) 唯一键 → 1062。
普通 SELECT 因过滤条件"看不见"该行，但唯一索引检查照常命中——这就是
"查不到却撞车"的完整解释。

### 13.3 修复（`backend/app/services/prompt.py`）
版本号是 prompt 的固有属性，且 prompt 归属已由 `_get_or_404` 做过租户校验，
不应受租户视图过滤影响。新增 `_next_version_number()`：改走 **Core 级查询**
（`select(func.max(prompt_versions.c.version_number))`，基于表对象而非 ORM 实体），
`with_loader_criteria` 只作用于 ORM 实体 SELECT，因此不注入租户条件，
始终取到真实最大版本号。

### 13.4 回归测试
`backend/tests/test_prompt_version_tenant_scope.py`：注册真实的全局租户过滤器 +
构造"历史版本行挂在其他租户"的场景 → 断言 `create_version` 生成 v2 而非撞键。
（修复前该场景必现 1062 等价错误。）prompt 相关后端测试合计 **8/8 通过**。

### 13.5 数据面要求
存量版本行的 `tenant_id` 需通过 `b3c4d5e6f7a8` 的幂等回填修正（详见 §12.3）。
若 alembic 显示该迁移已应用但数据未回填，可手工执行：
```sql
UPDATE prompt_versions pv JOIN prompts p ON pv.prompt_id = p.id
SET pv.tenant_id = p.tenant_id
WHERE pv.tenant_id IS NULL OR pv.tenant_id = '';
```
未回填时保存已可正常工作（本次代码修复），但详情页版本历史/当前版本会因
租户过滤看不到旧行——回填后即恢复。

---

## 14. 执行补遗四：测试超时 与 保存后无法返回列表

### 14.1 问题一：点击「运行测试」显示超时
**根因**：前端 axios 客户端默认 `timeout: 30000`（`src/api/client.ts`）。而生产 nginx
已配 `proxy_read_timeout 300s`、后端亦无同步超时（langchain-openai 默认 600s），
因此**唯一的 30s 瓶颈在前端**。模型推理超过 30s 时（本地 Ollama 首次调用需加载
模型时尤为常见），浏览器先放弃并报 `timeout of 30000ms exceeded`——用户看到的
"超时"即此。

**修复**：
1. `src/api/client.ts`：新增导出 `AI_REQUEST_TIMEOUT = 300_000`，与 nginx 对齐。
2. 对所有 AI 长耗时端点单独放宽超时（CRUD 仍为 30s）：
   `testPrompt`、`testProviderConnectivity`、`testModel`、`executeWorkflow`。
3. 后端 `config.llm_request_timeout: int = 120`（秒）；`utils/llm.py` 新增
   `resolve_llm_timeout()`（Ollama 保持 600s，远端供应商取 120s）与
   `_friendly_llm_error()`（超时/连接类异常转为中文提示，随 `LLMException`(502) 返回），
   `invoke_model` 与 `test_connectivity` 均已接入，避免请求悬挂到 10 分钟。
4. `PromptDetail` 在测试进行中展示"模型推理进行中…请勿关闭页面"提示。

**回归测试**：`backend/tests/test_llm_timeout.py`（4 用例）→ 4/4 通过。

### 14.2 问题二：保存后无法返回 Prompt 列表
**根因**：`PromptDetail` 页原本**没有任何返回列表的入口**（仅有"编辑"按钮）；
且 `PromptEditor` 保存后 `navigate(...)` 入栈，历史栈变为
「列表 → 编辑 → 详情」，浏览器后退会回到编辑页，造成"回不去列表"的观感。

**修复**：
- `PromptEditor`：保存/创建成功后改为 `navigate(path, { replace: true })`，
  编辑页不再留存于历史栈；
- `PromptDetail`：头部新增「返回列表」按钮，显式 `navigate('/prompts')`，
  不依赖浏览器历史。

### 14.3 验证
- 后端相关测试合计 **12/12 通过**；前端 vitest **4/4**；`tsc` 仅剩与本次无关的
  预存错误（`src/utils/request.ts:71`）。
- ESLint：本次改动文件**无新增错误**（`client.ts:31` 的 `as any`、
  `PromptDetail.tsx:58` 的 `set-state-in-effect` 均为改动前既有问题）。

---

## 15. 执行补遗五：详情页「查看」按钮点击无反应

### 15.1 现象
访问 `prompts/{id}` 详情页，点击版本历史中某行的「查看」按钮，
界面**没有任何变化**，用户判定按钮失效。

### 15.2 排查（用真实数据定位，未靠推断）
通过后端自身的数据库引擎直接读取该 prompt 的真实数据：

```
prompt : d0ac65cd-…  tenant_id=1  name=旅游规划  status=draft
versions: [ (v1, is_current=1, content_len=42) ]   ← 总数 = 1
```

即**该 prompt 只有 1 个版本**。而详情页的逻辑是：
`selectedVersion` 初始化为「当前版本」（`load()` 中 `find(v => v.is_current)`），
「查看」按钮的实现是 `setSelectedVersion(r)`（`PromptDetail.tsx:114`）。

于是点击时传入的 `r` **就是当前 state 里已有的同一个对象**，
`Object.is` 判定相等，**React 触发 bailout 跳过重渲染** —— 界面确实零变化。

结论：**按钮本身没有报错，是"点击目标已经是当前预览目标"导致的静默 no-op。**
当存在 ≥2 个版本、且点击的是非当前预览版本时，功能正常。

### 15.3 修复（`frontend/src/pages/Prompts/PromptDetail.tsx`）
让「查看」在任何情况下都产生**可见反馈**，并让"正在预览哪一版"始终可辨识：

1. 新增 `handleView(version)`：区分「切换到新版本」与「已在预览该版本」，
   两种情况都给出明确提示（`message.success('已切换到 vN')` /
   `message.info('正在预览 vN，内容见下方「版本内容」')`），并把预览区
   `scrollIntoView` 到可视范围；
2. 版本列新增「预览中」Tag，当前被预览的版本一眼可辨（与「当前」Tag 区分）；
3. 「查看」按钮在处于预览状态时渲染为 `type="primary"`，形成选中态；
4. 版本表格行用 `onRow` 加浅蓝底色，标记当前预览行。

> 设计取舍：未引入弹窗（Drawer/Modal）。页面本身已有「版本内容」内联预览区，
> 再加弹窗会造成同一内容两处展示；此处只需把"选中态 + 反馈"补齐。

### 15.4 新增组件级测试（本轮首次引入）
此前的测试均为纯逻辑测试，无法覆盖"点击后界面是否变化"。本轮补齐前端组件测试能力：

- 安装 `jsdom` + `@testing-library/react`（devDependencies，声明于 `frontend/package.json`）；
- `vitest.config.ts` 增加 `@vitejs/plugin-react` 以支持 TSX 测试文件的 JSX 转换；
- 新增 `src/pages/Prompts/PromptDetail.test.tsx`（`// @vitest-environment jsdom`），
  用 mock 替换 `@/api/prompt`、`@/api/ai-model`、`antd.message` 与 `@/components/CodeEditor`
  （monaco 无法在 jsdom 加载），断言：
  1. 默认预览当前版本，且该行出现「预览中」；
  2. 点击其他版本的「查看」→ 预览内容切换 + 提示"已切换到 v2"；
  3. **点击已预览版本的「查看」→ 出现"正在预览 v1"提示**
     （即本次修复的回归点；修复前该断言必然失败，因为旧代码完全不调用 `message`）。

> 踩坑记录：antd 会在两个中文字符之间自动插入空格，按钮的可访问名为
> `查 看` 而非 `查看`，测试需用 `/查\s*看/` 匹配。

### 15.5 验证状态
| 检查项 | 结果 |
|--------|------|
| 前端 vitest（含 3 条新组件测试） | ✅ **14/14 通过**（3 个测试文件） |
| `tsc -p tsconfig.app.json` | ✅ 新增文件类型通过；仅剩既有 `request.ts:71` |
| ESLint（`PromptDetail.tsx` / `PromptDetail.test.tsx` / `vitest.config.ts`） | ✅ 无新增错误；仅剩既有 `PromptDetail.tsx:60`（`set-state-in-effect`，HEAD 中已存在） |

### 15.6 遗留事项（未执行，等你决定）
1. **测试运行器的位置**：`vitest` 原先意外装在了仓库根目录（`AI-Studio/package.json`
   与 `AI-Studio/node_modules`），本轮已把 vitest/jsdom/@testing-library 正确安装进
   `frontend/`，`cd frontend && npm run test` 已可自洽运行。根目录那份属冗余，可删除
   （删除操作被你拒绝，故保留原样）。
2. **临时诊断脚本**：`backend/scripts/inspect_prompt_versions.py` 用于快速查看某 prompt
   的版本行，可留作排查工具，也可删除。
3. **数据面**：`prompt_versions.tenant_id` 若存在与所属 prompt 不一致的存量行，
   详情页版本历史仍会因 S3 租户过滤而看不到这些旧行（保存功能本身已不受影响）。

---

## 16. 执行补遗六：删除「查看」按钮（对 §15 的推翻与定案）

### 16.1 为什么 §15 的处理是错的
§15 用「点击无反应 → 补提示」的方式修，属于**给一个本无必要的控件打补丁**。
用户追问「这个按钮有什么用，就弹个提示框？」后重新审视，结论是：**该按钮应当删除。**

判定依据（均为当前代码即可验证的事实，非推断）：
1. 「查看」的唯一作用是 `setSelectedVersion(r)`，即把下方「版本内容」卡片换一版；
   而该卡片在 `load()` 中**默认就绑定当前版本**且**始终渲染** —— 按钮没有产出
   任何原本不存在的信息，只是把已经可见的内容再换一次。
2. 该 prompt 真实数据只有 1 个版本（见 §15.2），此时点击**必然零变化**。
   §15 加提示框本质是在替「按钮无意义」做兜底。
3. 它与同行的「激活」并列，看起来同级，但一个是视图切换、一个是写操作，
   并列会让人误判操作风险。

### 16.2 定案：删按钮，改「点行即预览」
「查看历史版本内容」这一**功能需求是真实的**（版本不可变，旧内容仅存于版本表），
因此删的是**按钮这个形态**，不是功能：

- 删除 `handleView` 与「查看」按钮，新增 `handleSelectVersion`：
  点击版本行即选中该版本用于预览，并 `scrollIntoView` 把预览区带入视野；
- 选中态沿用行浅蓝底色 + 「预览中」Tag，`cursor: pointer`；
- 表格下方补一行说明：「点击版本行可在下方查看该版本内容」（弥补行点击的可发现性）；
- 「操作」列只保留「激活」（仅非当前版本行显示，当前版本行显示 `—`）；
  其 `onClick` 增加 `e.stopPropagation()`，避免触发行选中而顺带改变预览目标。

### 16.3 必要的显式化（改动引入的新风险）
改为「点行即预览」后，`selectedVersion` 同时决定**预览内容**与**测试目标**，
这一耦合会变得更隐蔽。为此在「测试运行」卡片顶部显式标注
`测试版本：vN`，使测试对象永不处于无感知状态。

### 16.4 测试更新（`PromptDetail.test.tsx` 重写为 5 条）
原 3 条断言全部围绕「查看」按钮，已失效；新断言锁定新契约：
1. 默认预览当前版本 + 该行标「预览中」；
2. 点击其他版本行 → 预览内容切换，且「测试版本」同步跟随；
3. 重复点击已预览行 → 内容不变，但仍有 `scrollIntoView` 反馈（不是静默无反应）；
4. **版本行不再渲染「查看」按钮**（锁定删除决定，防止回退）+ 非当前行保留「激活」，
   当前行以 `—` 占位；
5. 点击「激活」只触发一次请求（验证行点击事件已被阻止冒泡）。

### 16.5 验证状态
| 检查项 | 结果 |
|--------|------|
| 前端 vitest（`promptSave` / `pluginMeta` / `PromptDetail` 三个文件） | ✅ **17/17 通过** |
| `tsc -p tsconfig.app.json` | ✅ 本次改动无新增类型错误；仅剩既有 `request.ts:71` |
| ESLint（`PromptDetail.tsx` / `PromptDetail.test.tsx`） | ✅ 无新增错误；仅剩既有 `PromptDetail.tsx:60`（`set-state-in-effect`，已核对 HEAD 第 57 行同一个 `useEffect`，非本次引入） |

### 16.6 一句话结论
「查看」按钮不是"做得不好"，而是**在这个页面里没有存在理由** —— 它的功能已被
常驻的版本内容区覆盖。删除它、把入口收敛到「点击版本行」，页面少一个死控件，
且"当前在看哪一版 / 将测试哪一版"都变得明确。

---

## 17. 执行补遗七：删「预览中」标签、让「操作」列按需出现

用户追问两个问题：**①「下面就是具体的 prompt，为什么还要显示「预览中」？」
②「按钮都没有了，为什么非要有一个操作列？」** 逐条回答如下，并据此改动。

### 17.1 Q1：「预览中」标签是冗余表达 → 删除
"下方显示的是哪一版"这个事实，页面上原本已有**两处**表达：

| # | 表达位置 | 说明 |
|---|---------|------|
| 1 | 版本行浅蓝底色 | 点选后由 `onRow` 的 `style.background` 呈现 |
| 2 | 内容卡片标题 | `版本内容 — v1`，直接写明版本号 |

「预览中」Tag 是**第三处**说同一件事的信号 —— 一个事实表述三遍属于噪声。
§16.2 加它的出发点是"给按钮补可见反馈"，但反馈本就该由已有元素（行底色、
卡片标题）承担，不该新增元素。**结论：删除该 Tag**，选中态只保留行底色。

### 17.2 Q2：「操作」列有正当用途，但当前实现有缺陷 → 按需渲染
「操作」列**不是装饰**，它承载的是 **「激活」= 把某个历史版本回滚为当前版本**，
这是一个真实的写操作（对应后端 `POST /{prompt_id}/versions/{version_id}/activate`），
与「查看」那种无产出的动作性质完全不同，因此不能一删了之。

但用户的质疑命中了一个真实缺陷：§16.2 让**当前版本行渲染了 `—` 占位**。
结果在只有一个版本的 prompt 上，整列每行都是 `—`，即"一整列的无操作"，
纯属噪声。

**修正规则（已实施）**：
- 当**不存在可操作的历史版本**（即所有版本都是当前版本）时，**整列不渲染**；
- 渲染时，当前版本行留**空单元格**，不再用 `—` 占位。

实现上改为在列定义数组之后条件 `push`，避免在 `render` 里输出占位符。

### 17.3 测试更新（`PromptDetail.test.tsx` → 7 条）
在 §16.4 五条的基础上调整：
1. 默认预览当前版本（改为断言**不存在**「预览中」文本）；
2. 点击其他版本行 → 内容切换、测试版本跟随，且**选中态由行底色表达**
   （断言 `style` 含 `background`，未选中行不含）；
3. 重复点击已预览行仍有 `scrollIntoView` 反馈；
4. 无「查看」按钮、「操作」列只承载「激活」，当前版本行**无按钮**（不再断言 `—`）；
5. 点击「激活」只触发一次请求；
6. **只有一个版本时不渲染「操作」列**（`queryByText('操作')` 为 null，其余列正常）；
7. **存在历史版本时才渲染「操作」列**。

### 17.4 验证状态（含一处环境受限，如实记录）
| 检查项 | 结果 |
|--------|------|
| `tsc -p tsconfig.app.json` | ✅ 本次改动无新增类型错误；仅剩既有 `request.ts:71` |
| 前端 vitest（`promptSave` + `pluginMeta`，node 环境） | ✅ **12/12 通过** |
| 前端 vitest（`PromptDetail.test.tsx`，DOM 环境） | ⚠️ **本机环境无法运行**（见 17.5），代码与断言已更新但未执行 |
| ESLint | ✅ 无新增错误（仅剩既有 `PromptDetail.tsx:60`） |

### 17.5 环境受限记录（与代码无关，供后续排查）
本轮组件测试**无法执行**，根因是环境而非代码：

- 现象：vitest 报 `Timeout waiting for worker to respond`，
  该超时是 vitest **硬编码**的 `START_TIMEOUT = 6e4`（60s），不可配置。
- 实测：`require('jsdom')` 耗时 **74–76 秒**（正常应 < 1s），三次测量一致；
  用 `Module._load` 打点定位到慢点在 `jsdom/living/nodes/Document-impl.js`（19s）
  与 `living/interfaces`（62s）等模块子树。
- 交叉验证：`require('react-dom')` 仅 229ms、`saxes`/`tough-cookie` 约 150–220ms、
  文件读取吞吐正常（2.3MB 文件 0.19s）⇒ **不是磁盘 IO，也不是全局变慢**。
- 排除环境替代方案：改用 `happy-dom` 后仍然超时；且用**纯逻辑测试**文件
  （`promptSave.test.ts`）配 `--environment=happy-dom` 也超时 ⇒
  结论是**当前环境下 DOM 测试环境初始化整体超过 60s**，与具体 DOM 实现无关。
  （`happy-dom` 试验已回退：`frontend/package.json` 与锁文件根条目均已复原，
  仅 `package-lock.json` 内 3 条孤立包条目与 `node_modules/happy-dom` 残留，
  原因是本沙箱的批量删除守卫会中断 npm 的清理阶段，npm 下次成功安装时自动清除。）
- 对照：20:25 时同一套测试曾以 4.91s 跑通 **17/17**，说明这是**环境状态的退化**，
  非代码引起。建议在环境恢复后（或换非外置卷路径）重跑本文件确认 7 条断言。

