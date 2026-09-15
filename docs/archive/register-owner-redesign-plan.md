# 注册默认租户管理员 — 重设计方案 B（受控自助）实施计划

> 目标：纠正「登录页注册的用户默认都是租户管理员」这一不合理设计。
> 采用**方案 B（受控自助）**：保留自助建租户，但引入**显式租户所有者（owner）语义**、**邮箱验证激活**、**显式权限声明**，替换原有的「默认塞 admin 角色 + `'admin' in role.code` 字符串匹配」脆弱实现。

## 一、设计要点（三项变更）

1. **注册即 owner，而非默认 admin 角色**
   - 注册时新建租户，并在 `tenants.owner_id` 显式记录创建者。
   - 不再「静默把 `tenant_admin` 角色塞给用户」作为默认行为；owner 的管理能力由 `tenant.owner_id == current_user.id` 推导，与「被显式提升的 admin 角色」解耦。
   - 租户内「添加成员」流程（`create_user`）维持默认 `tenant_member` 不变，消除「注册路径 vs 邀请路径」的不对称。

2. **邮箱验证后才激活管理员态**
   - 新增 `users.email_verified`（默认 `False`）。
   - 注册后账户处于待验证态：登录被拒绝并提示「请先验证邮箱」；`require_tenant_admin` 类守卫要求 `email_verified=True`。
   - 新增验证令牌表 + `/auth/verify-email`、`/auth/resend-verification` 端点。邮件发送依赖 SMTP 配置；未配置时提供开发态回退（注册响应/日志返回 token）。

3. **显式权限声明，替换字符串匹配**
   - `roles` 表新增 `is_admin: bool`（仅 `tenant_admin` 置 `True`）。
   - `require_tenant_admin` / `require_permission` / 前端 `canManageSystem` 改为基于 `is_admin` 或 `owner_id` 判定，移除 `'admin' in role.code`。

## 二、数据模型变更（需 Alembic 迁移）

| 表 | 字段 | 说明 |
|----|------|------|
| `users` | `email_verified: bool` | 默认 `False` |
| `tenants` | `owner_id: str(36) nullable` | FK→users.id，显式所有者 |
| `roles` | `is_admin: bool` | 默认 `False`，初始化 `tenant_admin` 时置 `True` |
| `email_verifications` | `token PK`, `user_id`, `expires_at`, `created_at` | 验证令牌存储 |

迁移需**实际执行**（`alembic upgrade head`）并验证结构（见第五节）。

## 三、后端改动

- `app/models/user.py` / `tenant.py` / `role.py`：新增字段。
- `app/schemas/auth.py`：RegisterForm 不变；新增 `VerifyEmailForm` / `ResendVerifyForm`。
- `app/services/user.py`：
  - `register_user`：建租户时写 `owner_id`；**不再**自动 `user_role` 插入 `tenant_admin`；生成验证令牌；`email_verified=False`。
  - 新增 `create_email_verification` / `verify_email` / `resend_verification`（含过期与幂等）。
  - `_init_builtin_roles`：`tenant_admin` 置 `is_admin=True`。
- `app/core/dependencies.py`：
  - `require_tenant_admin`：判定改为 `is_platform_admin OR tenant.owner_id == user.id OR any(role.is_admin)`。
  - `require_permission`：移除 `'admin' in role.code` 绕过分支，改为 `any(role.is_admin)`。
- `app/api/auth.py`：
  - `register`：注册后返回 `email_verified=False` 提示；开发态回退返回 `verification_token`。
  - 新增 `verify-email`（GET/POST）、`resend-verification`。
  - `login`：拒绝 `email_verified=False`（返回明确错误）。
- 配置项：`app/core/config.py` 增加 `REQUIRE_EMAIL_VERIFICATION`（默认 `True`）、`SMTP_*` 占位。

## 四、前端改动

- `src/types/api.ts`：`User` 增加 `email_verified`；`Role` 增加 `is_admin`。
- `src/utils/permission.ts`：`canManageSystem` 改为基于 `user.roles.some(r => r.is_admin)`（替换 `r.code.includes('admin')`）；如需要可叠加 `user.is_tenant_owner`。
- `src/stores/auth.ts`：注册后若 `email_verified=False`，跳转/提示邮箱验证页（新增 `pages/Login/VerifyEmail.tsx` 或模态）。
- 登录失败提示区分「未验证邮箱」。

## 五、执行与验证

1. 写模型 + Schema + 迁移 → **执行 `alembic upgrade head`**，用 `information_schema` 核对新列。
2. 实现 service / 依赖 / 路由 / 前端。
3. 单元测试（vitest + pytest）：
   - `canManageSystem`：owner（is_admin）、非 admin 成员、未验证 owner 被拒。
   - 后端：`register_user` 不再赋予 `tenant_admin` 角色、写入 `owner_id`、`email_verified=False`；`verify_email` 过期/幂等；`require_tenant_admin` 对 owner / admin 角色 / 未验证 的放行与拒绝；`login` 拒绝未验证。
   - 现有 37 个前端用例 + 后端相关用例保持通过。
4. 代码审查（可读性 / 性能安全 / 项目规范），重点：`is_admin` 与 `owner_id` 两路判定是否覆盖所有管理员入口，避免遗留 `'admin' in code`。

## 六、分阶段执行顺序

- 阶段 1：模型 + 迁移 + `is_admin`/`owner_id` 字段落地（含迁移执行验证）。
- 阶段 2：注册流程改为 owner 语义 + 邮箱验证令牌 + 端点。
- 阶段 3：`require_tenant_admin` / `require_permission` / `canManageSystem` 显式判定改造。
- 阶段 4：前端验证页 + 登录拦截提示。
- 阶段 5：单元测试 + 审查 + 文档归档。

## 七、风险与回滚

- 破坏性：现有自注册用户已持有 `tenant_admin` 角色；迁移需为既有租户回填 `owner_id`（取该租户首个 `tenant_admin` 用户）与 `roles.is_admin=True`，保证旧数据仍可管理。
- 回滚：迁移可逆（`alembic downgrade`）；新增端点与字段为增量，旧逻辑保留兼容路径。
- 依赖：邮件发送需 SMTP；未配置时走开发态 token 回退，不阻断注册链路。
