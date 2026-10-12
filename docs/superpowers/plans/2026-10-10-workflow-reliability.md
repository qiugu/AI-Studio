# Workflow Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate false “Workflow not found” responses, make graph edits with temporary node IDs save reliably, and fix adjacent workflow-editor validation and form-state defects before redeploying only affected applications.

**Architecture:** Keep UUIDs as strings from HTTP through persistence, let request schemas accept both persisted UUID references and editor-local temporary references, and resolve all edge references atomically inside `WorkflowService`. Keep authorization in route dependencies instead of adding a second administrator-only visibility rule. Extract frontend payload conversion into a pure function so editor state and API contracts can be tested without React Flow rendering.

**Tech Stack:** FastAPI, Pydantic v2, SQLAlchemy 2.0, pytest, React 19, TypeScript, React Flow, Ant Design, Vitest, Kubernetes.

## Global Constraints

- Preserve global tenant isolation and permission guards.
- Keep all persisted IDs as UUID v4 strings; temporary IDs exist only in update requests.
- Never persist an edge until both endpoints resolve to nodes in the submitted graph.
- Make a graph replacement atomic and roll back on failure.
- Do not restart MySQL, Redis, or Qdrant during deployment.

---

### Task 1: Reproduce API visibility and graph-save defects

**Files:**
- Create: `backend/tests/test_workflow_service.py`
- Modify: `backend/app/api/workflow.py`

- [x] **Step 1: Add a route-policy test proving a permitted non-admin can read and validate a draft workflow**

Exercise the route function with a fake service and an active non-admin role. The existing code must fail by raising `NotFoundException`.

- [x] **Step 2: Add schema tests for temporary and persisted edge references**

Assert `WorkflowUpdate` accepts `temp-*` references and UUID strings, while rejecting blank references.

- [x] **Step 3: Run focused tests and verify RED**

Run: `cd backend && ../.venv/bin/pytest -q tests/test_workflow_service.py`

Expected: failures from the draft visibility restriction and temporary edge UUID validation.

### Task 2: Make graph replacement UUID-safe and atomic

**Files:**
- Modify: `backend/app/schemas/workflow.py`
- Modify: `backend/app/services/workflow.py`
- Modify: `backend/app/repositories/workflow.py`
- Modify: `backend/app/api/workflow.py`
- Modify: `backend/tests/test_workflow_service.py`

- [x] **Step 1: Model all persisted IDs as strings and edge request references as validated strings**

Use a small validator that accepts either a canonical UUID string or the `temp-` editor namespace. Response IDs remain plain strings, matching ORM models and the documented project convention.

- [x] **Step 2: Resolve edge endpoints from submitted node references**

For every submitted node, create a replacement row and map its `temp_id` or prior persisted ID to the new UUID. Reject duplicate references, missing endpoints, and self-inconsistent graphs with `ValidationException`.

- [x] **Step 3: Replace nodes and edges in one transaction**

Delete existing edges first, then nodes, create replacements, resolve and create edges, commit once, expire relationship state, and roll back on any exception.

- [x] **Step 4: Remove the administrator-only draft visibility override**

The existing `require_permission` and tenant filter define access. A user with workflow read permission can read/validate tenant drafts; execution remains restricted to published workflows by the engine.

- [x] **Step 5: Run focused backend tests and verify GREEN**

Run: `cd backend && ../.venv/bin/pytest -q tests/test_workflow_service.py tests/test_workflow_llm_node.py`

Expected: all pass.

### Task 3: Stabilize editor payloads and node configuration

**Files:**
- Create: `frontend/src/pages/Workflows/workflowPayload.ts`
- Create: `frontend/src/pages/Workflows/workflowPayload.test.ts`
- Modify: `frontend/src/pages/Workflows/WorkflowEditor.tsx`
- Modify: `frontend/src/pages/Workflows/NodeConfigPanel.tsx`
- Modify: `frontend/src/types/workflow.ts`
- Modify: `frontend/src/pages/Workflows/NodeConfigPanel.test.tsx`

- [x] **Step 1: Add failing pure payload tests**

Cover persisted UUID nodes, temporary nodes, mixed edges, labels/conditions, and ensure transient React callbacks are never serialized.

- [x] **Step 2: Extract and use `buildWorkflowGraphPayload`**

Keep edge endpoints as strings and add a `temp_id` for every submitted node so the backend can map both new and existing graph references after replacement.

- [x] **Step 3: Reset the node form when switching nodes and exclude `name` from config**

Reset stale node-type fields before applying the selected node config. Destructure `name` from validated values and persist only actual config fields.

- [x] **Step 4: Replace the knowledge-base numeric ID control with a string control**

Use a UUID-capable text input now; do not silently coerce identifiers to numbers.

- [x] **Step 5: Surface the backend validation message on save failure**

Prefer `error.response.data.message` over the generic “保存失败”.

- [x] **Step 6: Run focused frontend tests and verify GREEN**

Run: `cd frontend && npm test -- src/pages/Workflows/workflowPayload.test.ts src/pages/Workflows/NodeConfigPanel.test.tsx`

Expected: all pass.

### Task 4: Regression, local preview, and deployment

**Files:**
- Modify only files needed by failures found above.

- [x] **Step 1: Run backend workflow tests and broader backend suite**

Run: `cd backend && ../.venv/bin/pytest -q tests/test_workflow_service.py tests/test_workflow_llm_node.py`

Run: `cd backend && ../.venv/bin/pytest -q`

- [x] **Step 2: Run frontend tests, lint, and production build**

Run: `cd frontend && npm test`

Run: `cd frontend && npm run lint`

Run: `cd frontend && npm run build`

- [x] **Step 3: Reproduce the complete local workflow lifecycle**

Create a workflow as a permission-bearing non-admin, open it immediately, add/edit/connect nodes, save, reload, validate, and confirm no false 404 or schema 422.

- [x] **Step 4: Build unique ARM64 backend and frontend images**

Use immutable deployment tags. Because Celery shares the backend image, update it together with the backend while leaving stateful services untouched.

- [x] **Step 5: Import, smoke-test, and roll out only changed applications to `192.168.99.131`**

Update `backend`, `celery-worker`, and `frontend`; verify rollout status, API health, workflow lifecycle, and deployed frontend asset markers. Remove temporary transfer files and importer pods.
