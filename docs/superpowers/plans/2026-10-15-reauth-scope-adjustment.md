# Reauthentication Scope Adjustment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restrict current-password confirmation to sensitive credentials and high-risk authorization/account lifecycle changes, while removing it from ordinary metadata and plugin endpoint edits.

**Architecture:** Keep the server-side reauthentication helper as the enforcement point. Add explicit field-level predicates in the plugin and AI provider services, and make role reauthentication conditional on permission/lifecycle impact. Keep existing account, role-permission, owner-transfer, and destructive membership protections unchanged. Update the UI only where it currently prompts for a broader operation than the backend should protect.

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic v2, React 19, TypeScript, Vitest, pytest.

## Global Constraints

- Preserve service-layer authorization checks; removing a password prompt must not remove RBAC permission checks.
- Sensitive credentials remain Fernet-encrypted and must never be returned in plaintext.
- Plugin endpoint CRUD remains protected by `plugin.endpoint_bind`, but does not require current-password confirmation.
- Existing unrelated workflow changes in the working tree must not be modified.
- Add regression tests before implementation and run focused plus relevant frontend/backend test suites.

### Task 1: Define backend reauthentication boundaries with failing tests

**Files:**
- Modify: `tests/test_sensitive_mutation_reauth.py`
- Test: `tests/test_sensitive_mutation_reauth.py`

- [x] **Step 1: Add tests for ordinary role and provider metadata changes without password.**
- [x] **Step 2: Add tests for plugin ordinary configuration and endpoint mutations without password, while keeping plugin API-key updates protected.**
- [x] **Step 3: Run the focused tests and verify they fail for the current broad checks.**

### Task 2: Implement field-level backend reauthentication

**Files:**
- Modify: `app/services/plugin.py`
- Modify: `app/services/ai_provider.py`
- Modify: `app/services/role.py`

- [x] **Step 1: Add explicit helpers that identify sensitive plugin/provider configuration fields.**
- [x] **Step 2: Require plugin reauthentication only when incoming or removed configuration names are sensitive.**
- [x] **Step 3: Require AI-provider reauthentication for API keys or explicitly sensitive configuration keys, not arbitrary metadata config.**
- [x] **Step 4: Require role reauthentication only for permission-bearing creation, permission-impacting updates, status changes, deletion, or permission assignment; allow name/description edits without it.**
- [x] **Step 5: Run the focused backend tests and verify they pass.**

### Task 3: Align frontend prompts and request payloads

**Files:**
- Modify: `frontend/src/pages/Plugins/PluginConfig.tsx`
- Modify: `frontend/src/pages/AIModels/ProviderForm.tsx`
- Modify: `frontend/src/pages/System/Roles.tsx`
- Modify: `frontend/src/types/plugin.ts`

- [x] **Step 1: Remove the current-password requirement from the plugin endpoint/connection form when only non-sensitive connection metadata is being saved; retain it for sensitive credential changes.**
- [x] **Step 2: Make role create/edit prompt only when the submitted change affects permissions or lifecycle status.**
- [x] **Step 3: Keep provider credential confirmation aligned with API-key or sensitive-config changes.**
- [x] **Step 4: Add frontend tests for the changed reauthentication boundaries.**
- [x] **Step 5: Run focused frontend tests, type-check, and lint.**

### Task 4: Reconcile documentation and run regression verification

**Files:**
- Modify: `docs/superpowers/plans/2026-10-13-rbac-tenant-permission-plan.md`
- Modify: `docs/plugin-usage-flow-review.md`
- Modify: `tests/test_sensitive_mutation_reauth.py`

- [x] **Step 1: Document the final boundary: ordinary metadata/endpoint changes do not require passwords; credentials and high-risk authorization changes do.**
- [x] **Step 2: Run the complete relevant backend regression tests.**
- [x] **Step 3: Run the complete relevant frontend regression tests and production checks.**
- [x] **Step 4: Review the diff to confirm unrelated workflow changes remain untouched.**

## Verification note

Focused backend regression: `54 passed`; full backend suite: `1155 passed, 4 skipped, 1 failed` because the local Hugging Face cache lacks `BAAI/bge-base-zh-v1.5` for the unrelated embedding test. Frontend: `31 files / 162 tests passed`, `npm run build`, and `npm run lint` passed.
