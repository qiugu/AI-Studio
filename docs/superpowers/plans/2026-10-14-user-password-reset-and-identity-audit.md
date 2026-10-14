# 用户密码重置与身份审计 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将密码修改收敛为当前用户自己的账号操作，放在右上角账号菜单；用户管理只负责成员生命周期和角色治理，并让昵称变更始终保留可追溯的稳定身份快照。

**Architecture:** 用户编辑表单只处理状态，角色通过独立权限操作管理；密码修改通过右上角账号菜单调用当前用户专属接口，要求当前密码再认证并撤销旧会话。忘记密码仍使用数据库只保存哈希的一次性令牌；审计使用 `target_id` 加邮箱和昵称前后快照，不记录任何密码或密码哈希。

**Tech Stack:** FastAPI、SQLAlchemy 2.0、Alembic、Pydantic v2、React 19、TypeScript、Ant Design、Vitest。

## Global Constraints

- 用户管理和租户管理不提供成员密码修改入口。
- 当前用户只能从右上角账号菜单修改自己的密码。
- 密码重置令牌只保存哈希，单次使用，默认 1 小时过期，并在成功重置后使旧授权状态失效。
- 审计日志必须保留不可变用户 ID、邮箱快照、昵称变更前后值；禁止保存密码、密码哈希或重置令牌。
- 遵循项目统一响应、异常、租户隔离和 `require_permission` 约定。
- 修改前端时保留现有 Ant Design 风格，并为高风险操作给出清晰的安全说明。

---

### Task 1: 锁定管理员不能直接设置密码与身份快照审计

**Files:**
- Modify: `tests/test_user_roles.py`
- Modify: `tests/test_authorization_audit.py`
- Modify: `app/services/user.py`

**Interfaces:**
- `update_user(...)` 接受 `UserUpdate`，但当请求包含密码字段时必须拒绝。
- 用户昵称变更的 `USER_UPDATED` 审计元数据包含 `target_user_id`、`target_email`、`nickname_before`、`nickname_after`，并且不包含密码数据。

- [x] **Step 1: Write the failing tests**

添加两个测试：管理员带 `password` 更新成员时抛出 `ValidationException`；昵称变更后审计日志保存稳定身份和前后快照。

- [x] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest -q tests/test_user_roles.py tests/test_authorization_audit.py`

Expected: 新增的密码测试失败（当前实现会直接修改密码），昵称快照断言失败。

- [x] **Step 3: Write minimal implementation**

在 `update_user` 中移除密码写入逻辑，包含密码字段时抛出明确的 `ValidationException`；在修改昵称前保存旧值，并将邮箱和昵称快照写入结构化审计元数据。

- [x] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest -q tests/test_user_roles.py tests/test_authorization_audit.py`

Expected: PASS。

---

### Task 2: 添加一次性密码重置令牌和后端接口

**Files:**
- Create: `app/models/password_reset.py`
- Modify: `app/models/__init__.py`
- Create: `alembic/versions/q1_password_reset_tokens.py`
- Modify: `app/schemas/user.py`
- Modify: `app/services/user.py`
- Modify: `app/api/user.py`
- Modify: `app/api/auth.py`
- Modify: `app/utils/email.py`
- Modify: `tests/test_user_roles.py`
- Create: `tests/test_password_reset.py`

**Interfaces:**
- `POST /api/users/{user_id}/password-reset`：有 `user.update` 权限的租户管理员发起重置，要求当前密码再认证；不接收新密码。
- `POST /api/auth/password-reset`：使用一次性令牌提交新密码，成功后令牌失效并递增目标用户 `authz_version`。
- 数据库表 `password_reset_tokens`：`token_hash`、`user_id`、`requested_by`、`expires_at`、`used_at`、时间字段。

- [x] **Step 1: Write the failing tests**

覆盖：重置请求不返回明文令牌（SMTP 已配置时）；令牌只能使用一次；过期令牌被拒绝；新密码成功后旧令牌失效且 `authz_version` 增加；重置审计不含秘密。

- [x] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest -q tests/test_password_reset.py`

Expected: FAIL，因为模型、服务和接口尚不存在。

- [x] **Step 3: Write minimal implementation**

使用 `secrets.token_urlsafe` 生成令牌，使用 SHA-256 哈希入库；发起时撤销同一用户未使用令牌，邮件发送失败时保持统一成功响应且不泄露用户存在性；消费时锁定令牌和用户、校验有效期、哈希匹配、设置新密码、标记已用并递增授权版本。

- [x] **Step 4: Add and run the Alembic migration test**

Run: `.venv/bin/pytest -q tests/test_password_reset.py tests/test_rbac_permission_migration.py`

Expected: PASS。

---

### Task 3: 对齐前端用户管理、账号菜单与审计展示

**Files:**
- Modify: `frontend/src/types/api.ts`
- Modify: `frontend/src/api/user.ts`
- Modify: `frontend/src/pages/System/Users.tsx`
- Modify: `frontend/src/pages/System/AuditLogs.tsx`
- Modify: `frontend/src/api/audit.ts`
- Create or modify: `frontend/src/pages/System/Users.test.tsx`

**Interfaces:**
- 编辑用户弹窗不显示密码和昵称字段；只保留状态，角色使用独立管理操作。
- 右上角账号下拉菜单新增“修改密码”，由当前用户输入当前密码和新密码。
- 审计日志显示目标用户 ID、邮箱快照以及昵称变更前后值。

- [x] **Step 1: Write the failing frontend tests**

断言编辑弹窗不存在“密码”和“昵称”输入；右上角账号菜单能调用本人修改密码 API；审计行能显示稳定 ID 和昵称变化。

- [x] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npm run test -- --run src/pages/System/Users.test.tsx`

Expected: FAIL，因为现有编辑表单仍包含密码输入且没有重置 API。

- [x] **Step 3: Write minimal implementation**

从用户管理表单移除密码和昵称编辑项；新增当前用户修改密码 API 与右上角账号菜单弹窗；扩展 `AuditLog` 类型和表格展示快照。

- [x] **Step 4: Run frontend checks**

Run: `cd frontend && npm run test -- --run && npm run lint && npx tsc --noEmit && npm run build`

Expected: 全部通过。
---

### Task 4: 全量回归和文档同步

**Files:**
- Modify: `docs/api-design.md`
- Modify: `docs/database-design.md`
- Modify: `docs/frontend-design.md`

- [x] **Step 1: Document the security boundary**

说明密码修改只能由当前用户从右上角账号菜单发起；说明稳定用户 ID、邮箱快照和昵称历史的审计要求。

- [x] **Step 2: Run backend and repository checks**

Run: `.venv/bin/pytest -q --deselect=tests/test_embedding.py::test_embedding_client`, `python -m compileall -q app`, `git diff --check`, `docker compose config --quiet`, `kubectl kustomize deploy/k8s >/dev/null`。

Expected: 全部通过。
