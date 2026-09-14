# 编码约定对齐改造计划（方案 B 落地）

> 目标：让 `CLAUDE.md` / `AGENTS.md` 的编码约定与代码实现**一致**，归零低风险约定违规，抽取高价值复用查询；**不追求**对 88 处一次性查询做机械重构。

---

## 1. 背景与目标

评审（`docs/review/`）指出两条约定被系统性绕过：

- **S3**：`CLAUDE.md` 要求"所有数据访问必须通过 `BaseRepository`"，实际 services 层有 49 处（实测约 88 处）裸 `self.db.query/execute`。
- **C1**：`CLAUDE.md` 要求"禁止直接抛 `HTTPException`"，实际 25 处裸 `raise HTTPException`。

此前 P0/P1 整改以**补偿性控制**路线收口了*影响*：

- S3：新增 `core/tenant_scope.py`（`do_orm_execute` + `with_loader_criteria` 全局过滤器），在 ORM 执行层自动注入 `tenant_id`，**从机制上消除了跨租户泄露风险**（含评审确证遗漏的 `workflow_engine.py:255`、`agent.py:82,514`）。
- C1：新增全局 `HTTPException` 处理器（`main.py:104`），裸 `HTTPException` 也返回统一信封 `{code, message, data}`；并移除 `api/agent.py` 中 `AppException → HTTPException` 的反向降级。

因此**安全与契约可用性已达标**，但两条约定在**字面上仍被违反**，且 `CLAUDE.md` 把此事写成了"已知偏差"，导致文档与实现持续打架、评审反复误判为"系统性违规"。

本计划解决的是**约定符合性 + 文档对齐 + 高价值抽取**，而非重新引入已被证明更脆弱的"强制全量 Repository"。

---

## 2. 社区最佳实践依据

1. **SQLAlchemy `Session` 本身即 Unit of Work + Repository 抽象**。在它之上包一层泛型 `BaseRepository`（`get/filter/create/update/delete`）常退化为"换皮"调用（`repo.filter(...)`），对查询密集型、大量一次性查询的应用无收益、反增维护成本（贫血包装反模式）。
2. **集中强制隔离 > 依赖"记得调用"**。租户隔离的正确保障是"无法被绕过"，而非"每个 Service 都记得走 Repository"——后者正是 49→88 处违规出现的根因。
3. **按查询的复杂度 / 复用度分级**，而非一刀切：
   - 简单单模型 CRUD / 一次性过滤 → 直接用 `Session`（已被全局过滤器兜底租户隔离）；
   - 跨模型聚合、复杂条件、多处复用 → 抽到 `Repository` / `Query Object`；
   - 含不变量的写操作 → `Repository` 显式方法，把业务规则收敛到一处。
4. **CI lint 防回归**应检查"查询是否绕过租户作用域"，而非禁止 `db.query`（全局过滤器已保证，故优先级低）。

---

## 3. 范围

**In scope**
- C1：归零 `api/` 下 4 处残留 `raise HTTPException`。
- 文档：重写 `CLAUDE.md` / `AGENTS.md` 相关约定 + 修正 `docs/review/` 的"已修复"口径。
- 抽取：1 个共享租户/公共过滤 helper + 2 个高频 `Repository`。

**Out of scope**
- 对 88 处一次性查询做机械重构（过度设计，无收益）。
- 改动 `core/tenant_scope.py` 的全局过滤器（它是正确的，已验证）。

---

## 4. 分阶段执行计划

### Phase 0 · 基线核对
- 运行测试基线，确认 `test_tenant_scope`（12）、`test_response_envelope`（3）、`test_rate_limit_ip`（4）通过。
- 读 `repositories/base.py` 确认 `_tenant_filter()` / `_tenant_or_public_filter()` 现有签名，供 Phase 3a 复用。

### Phase 1 · C1 归零（4 处 `raise HTTPException`）
位置均在 `backend/app/api/knowledge.py`：

| 行 | 原语义 | HTTP | 替换为 |
|----|--------|------|--------|
| 170 | 不支持的文件类型 | 400 | `BadRequestException`（保留 400，低风险） |
| 184 | 文件头 magic 与扩展名不符 | 400 | `BadRequestException` |
| 195 | 上传超过大小限制 | 413 | 新增 `PayloadTooLargeException(413, "PAYLOAD_TOO_LARGE")`（additive，可复用） |
| 249 | 非法 `status` 枚举值 | 400 | `BadRequestException` |

- 替换后如 `knowledge.py` 不再需要 `HTTPException` 导入，则清理 import。
- 新增/补充测试：断言知识库上传路径的错误响应体含 `code`/`message`/`data`，且 **HTTP 状态码保持不变**（验证 `PayloadTooLargeException` 经全局处理器后仍为 413）。
- 验收：`grep -rc "raise HTTPException" backend/app/api/` 全部为 0。

### Phase 2 · 文档对齐
- **`CLAUDE.md`**：将"已知偏差"段落改为正式架构说明，措辞建议：
  > 所有查询必须经由全局租户作用域（已在 `core/tenant_scope.py` 强制注入，不可绕过）；简单单模型查询允许直接使用注入的 `Session`；跨模型、复杂或复用的查询优先抽到 `Repository` / `Query Object`；**禁止手写租户过滤条件**（由全局过滤器统一处理）。
- **`AGENTS.md`**：在"关键技术约定"概述中同步上述表述。
- **`docs/review/README.md`**：将 S3 / C1 的"✅ 已修复"口径修正为"影响已缓解（安全隔离 / 契约统一），字面合规由 `plan-convention-alignment.md` 收口"，并更新进度表。
- **`docs/review/01-backend.md`**：在 C1 / S3 章节末尾加"后续：见 `docs/plan-convention-alignment.md`"。

### Phase 3 · 高价值查询抽取（1 helper + 2 Repository）
> 选择标准：仅抽取**跨 Service 复用 ≥ 2 次**或**含不变量**的查询；`admin.py` 计数、`user.py` 角色装配等一次性查询保持 `Session` 直查，不强制入仓。

**3a · 共享租户/公共过滤 helper（最高 ROI）**
- 在 `core/tenant_scope.py` 导出 `public_or_tenant_filter(model, tenant_id, include_public)`，复用既有 `tenant_or_public_clause` / `tenant_or_flagged_public_clause`（已实现于同文件）。
- 替换以下散落副本：
  - `services/plugin.py:_base_filter`（46–53 行）
  - `services/ai_model.py:_base_filter`（20–27 行）
  - `services/prompt.py:239` 内联 `(AIModel.tenant_id == self.tenant_id, AIModel.tenant_id.is_(None))`
  - `services/agent.py:162,228` 内联 `(AIModel.tenant_id == self.tenant_id) | (AIModel.tenant_id.is_(None))`
- 行为不变，消除 4+ 处语义分歧，单一事实来源。

**3b · `ModelRepository`（AIModel + AIProvider）**
- 整合 `agent.py` / `workflow_engine.py` / `ai_model.py` / `ai_provider.py` 中按 id 查询与 `list(include_public)`。
- 提供 `get_active(model_id, tenant_id)` / `list_for_tenant(tenant_id, include_public)`。
- 保留原查询语义，不改 HTTP 行为。

**3c · `PluginEndpointRepository`**
- 整合 `plugin.py` + `agent.py` 中约 13 处 `PluginEndpoint` 查询。
- 提供 `get_by_id` / `list_for_plugin` / `resolve(endpoint_id, tenant_id)`。

### Phase 4 · 验证与审查
- **单元测试**：`pytest` 全量；聚焦 `test_tenant_scope`(12) / `test_response_envelope`(3) / `test_rate_limit_ip`(4) + 新增 knowledge 错误响应断言。
- **编译检查**：`py_compile` 全部改动文件。
- **前端**：本计划无前端改动；若涉及接口契约变化，运行 `eslint`。
- **代码审查清单**（按用户规范要求逐项过）：
  - a. 可读性：是否有足够注释，尤其 `public_or_tenant_filter` 的语义；
  - b. 性能 / 安全：查询是否仍走索引、租户条件是否仍在（防回归越权）；
  - c. 风格 / 最佳实践：是否遵循项目约定（统一响应、异常体系、全改动经 `BaseRepository` 或既有 helper）。

---

## 5. 风险与权衡

- **C1 状态码变化**：`ValidationException` 为 422，原代码为 400。建议优先 `BadRequestException`（保留 400）以最小化前端副作用；仅当确认前端不依赖具体状态码时改用 `ValidationException`。**待评审确认。**
- **Repository 抽取误改语义**：每步保留原查询行为并补测试覆盖，避免回归。
- **不触碰全局过滤器**：避免破坏已验证的隔离机制。

---

## 6. 验收标准（Definition of Done）

- [ ] `grep -rc "raise HTTPException" backend/app/api/` 全部为 0
- [ ] `CLAUDE.md` / `AGENTS.md` 约定与实现一致，无"已知偏差"措辞
- [ ] 共享 `public_or_tenant_filter` 替换全部手写租户/公共条件（含 `plugin` / `ai_model` / `prompt` / `agent`）
- [ ] `ModelRepository` + `PluginEndpointRepository` 落地且有测试
- [ ] 全量单元测试通过；`py_compile` 全部改动文件通过
- [ ] 代码审查清单（可读性 / 性能安全 / 风格）通过

---

## 7. 待评审确认点

1. **C1 状态码策略**：保留 400（`BadRequestException`）还是改 422（`ValidationException`）？建议前者（低风险）。
2. **Repository 抽取范围**：本计划列了 3a+3b+3c 三项；若想更小步，可先只做 **3a（共享 helper）** 这一项最高 ROI 改动，3b/3c 后续单独评估。
3. Phase 2 文档改写是否同步修正 `docs/review/` 的"已修复"口径（建议同步，避免遗留误导）。

---

## 8. 执行状态（2026-09-13）

用户评审确认：C1 保留 400（`BadRequestException`）；仅先做价值最高的 **3a**（共享 helper），3b/3c 暂缓。

| 阶段 | 状态 | 说明 |
|------|------|------|
| Phase 1 · C1 归零 | ✅ 已完成 | `api/knowledge.py` 4 处裸 `HTTPException` 改为 `BadRequestException`（400 / `BAD_REQUEST`）；`api/` 下 `raise HTTPException` 经测试静态扫描归零 |
| Phase 2 · 文档对齐 | ✅ 已完成 | `CLAUDE.md` 多租户/异常"已知偏差"改为正式分层约定；`AGENTS.md` 多租户约定对齐；`docs/review/README.md` 与 `01-backend.md` 的 S3/C1 口径修正为"影响已缓解 + 字面合规收口" |
| Phase 3a · 共享 helper | ✅ 已完成 | `core/tenant_scope.py` 新增 `public_or_tenant_filter(model, tenant_id, include_public)`；收敛 `plugin.py` / `ai_model.py` 的 `_base_filter`、`prompt.py:239`、`agent.py:162/228` 散落副本；对 Plugin 采用更严格的 `tenant_or_flagged_public_clause`，消除与 model 层的语义分歧 |
| Phase 3b / 3c · Repository | ⏸ 暂缓 | 按用户决策仅做 3a；`ModelRepository` / `PluginEndpointRepository` 后续单独评估 |
| Phase 4 · 验证 | ✅ 已完成 | 聚焦测试 25 passed（含 `test_public_or_tenant_filter` 5 项 + `BadRequestException` 信封 1 项 + 基线 `test_tenant_scope` 12 / `test_rate_limit_ip` 4）；受影响 service 测试 120 passed；全部改动文件 `py_compile` 通过 |

**代码审查结论（可读性 / 性能安全 / 风格）**
- 可读性：`public_or_tenant_filter` 含完整 docstring，说明单一事实来源与分支语义；各 `_base_filter` 用一行注释标注意图。
- 性能/安全：AIModel 公共查询走 `tenant_id` 索引等值 + `IS NULL`；Plugin 公共查询改为更严格的 `(tenant_id IS NULL AND is_public)`（与全局过滤器一致，消除越权/误放行风险），请求上下文下全局过滤器已强制该条件，逻辑 AND 幂等、无回归；未引入新全表扫描。
- 风格：复用既有 `AppException`/`BadRequestException` 与 `tenant_scope` 规范函数，清理了未使用的 `or_` / `HTTPException` / `status` 导入，未手写租户过滤条件。
