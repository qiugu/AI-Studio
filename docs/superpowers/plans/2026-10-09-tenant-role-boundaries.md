# Tenant Role Boundaries Implementation Plan

**Goal:** Enforce the agreed platform-admin, tenant-admin, and tenant-member responsibilities across tenant provisioning, backend APIs, and frontend navigation.

**Architecture:** Platform tenant provisioning creates a tenant and its first tenant-admin account atomically because users currently belong to exactly one tenant. Tenant RBAC guards then distinguish platform administrators from tenant users and apply only to active roles in the user's tenant. The frontend mirrors those boundaries, while public self-service registration is disabled.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, Pydantic v2, React 19, TypeScript, React Router, Ant Design.

## Global Constraints

- Tenant and role ownership is enforced by tenant ID on the server.
- Platform administrators may create tenants and the initial tenant administrator only.
- Tenant administrators manage members, roles, tenant settings, and tenant system information.
- Tenant members use business features only.
- Preserve existing database records and unrelated working-tree changes.

### Task 1: Provision tenant and initial administrator

**Files:**
- Modify: `backend/app/schemas/admin.py`
- Modify: `backend/app/services/admin.py`
- Modify: `backend/app/api/admin.py`
- Modify: `frontend/src/types/api.ts`
- Modify: `frontend/src/pages/Admin/TenantList.tsx`

- [x] Add required initial-admin email and password to the tenant creation request.
- [x] Create tenant, built-in roles, initial admin user, owner link, and user-role link in one transaction.
- [x] Keep only tenant creation in the platform-admin API; remove tenant listing/details and all update/delete/quota/public-model endpoints.
- [x] Simplify platform UI to a tenant creation form and remove links to platform tenant details.

### Task 2: Enforce server-side role boundaries

**Files:**
- Modify: `backend/app/core/dependencies.py`
- Modify: `backend/app/api/audit.py`
- Modify: `backend/app/api/knowledge.py`
- Modify: `backend/app/api/agent.py`
- Modify: `backend/app/api/workflow.py`
- Modify: `backend/app/api/ai_provider.py`
- Modify: `backend/app/api/ai_model.py`
- Modify: `backend/app/api/prompt.py`
- Modify: `backend/app/api/plugin.py`
- Modify: `backend/app/services/role.py`

- [x] Add a tenant-user guard that rejects platform administrators and requires active roles belonging to the user's tenant.
- [x] Make fine-grained permissions require tenant-user membership and use only active roles from the current tenant.
- [x] Restrict tenant system information, dashboard, token statistics, and audit endpoints to tenant administrators.
- [x] Ensure custom role management cannot create an `is_admin` role and permission assignment rejects unknown permission IDs.

### Task 3: Align frontend navigation and account onboarding

**Files:**
- Modify: `frontend/src/components/Layout/Sidebar.tsx`
- Modify: `frontend/src/utils/permission.ts`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/pages/Login/index.tsx`
- Modify: `frontend/src/pages/Admin/TenantList.tsx`
- Modify: `backend/app/api/auth.py`

- [x] Show platform tenant creation only to platform administrators and tenant management only to tenant administrators.
- [x] Remove the self-service registration UI and disable its backend endpoint; retain verification for already issued tokens.
- [x] Restrict platform-admin UI routes to tenant creation and prevent business pages from being used by platform-only accounts.

### Task 4: Review and verify

**Files:**
- Review: `backend/app/api/`
- Review: `frontend/src/`

- [x] Inspect remaining API routes for login-only access that allows platform administrators or exposes tenant system information to members.
- [x] Run syntax/type/build checks available in the environment and inspect `git diff --check`.
- [x] Record verification scope: Python syntax compilation and frontend production build passed; test suites were not run because testing was not requested.
