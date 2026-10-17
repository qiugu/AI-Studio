# Agent Observability and Chat Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make knowledge bases usable by default in Agent conversations, expose tool execution in the live chat and dashboard, and redesign the Agent workspace with a complete assistant-side bubble and a distinctive enterprise control-room visual language.

**Architecture:** Keep the existing SSE transport and persist tool execution summaries on the assistant `messages.tool_calls` JSON field already present in the schema. The backend will synthesize default knowledge tools for tenant knowledge bases with indexed content when an Agent has no explicit knowledge binding, emit typed tool lifecycle SSE events, and aggregate persisted tool calls for dashboard observability. The frontend will extend the SSE callback contract, render an expandable tool trace inside each assistant bubble, and reorganize the Agent chat and dashboard around a dark control-room surface with focused cyan execution accents.

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic, existing SSE helper; React 19, TypeScript, Ant Design 6, Vitest, existing Markdown/citation components.

## Global Constraints

- Preserve tenant isolation and use the existing `KnowledgeBase` tenant/deleted/content filters.
- Preserve the existing citation marker contract and `citations` SSE events.
- Use the existing `Message.tool_calls` JSON field; do not add a new persistence table or endpoint.
- Tool execution telemetry must be summarized and bounded; never persist raw stack traces or unbounded payloads.
- Agent reply messages must render as a left-aligned assistant bubble, with visible keyboard focus and reduced-motion support.
- Follow the project's unified response and SSE conventions; no hand-built SSE frames.

### Task 1: Default knowledge tools and typed tool lifecycle events

**Files:**
- Modify: `app/services/agent.py`
- Modify: `app/api/agent.py`
- Test: `tests/test_agent_tool_events.py`

**Interfaces:**
- `AgentService._effective_agent_tools(agent) -> list` returns explicit enabled tools plus default knowledge tools when no knowledge tool is configured.
- `_iter_tool_agent_output(...)` yields `tool_start`, `tool_end`, and `tool_error` records with `call_id`, `tool`, bounded `input`/`output`, and `status`.
- The stream API maps those records to same-named SSE events and stores completed summaries in `Message.tool_calls`.

- [ ] **Step 1: Write failing tests for default knowledge tools and lifecycle event payloads.**
- [ ] **Step 2: Run the focused tests and confirm they fail for the missing default/event behavior.**
- [ ] **Step 3: Implement the effective-tool synthesis, bounded serialization, event forwarding, and message persistence.**
- [ ] **Step 4: Run the focused backend tests and the existing Agent citation tests.**

### Task 2: Frontend event contract and live tool trace

**Files:**
- Modify: `frontend/src/types/agent.ts`
- Modify: `frontend/src/utils/streamRequest.ts`
- Modify: `frontend/src/pages/Agents/AgentChat.tsx`
- Modify: `frontend/src/components/Chat/MessageBubble.tsx`
- Modify: `frontend/src/components/Chat/ChatContainer.tsx`
- Modify: `frontend/src/pages/Agents/AgentChat.css`
- Test: `frontend/src/utils/streamRequest.test.ts`
- Test: `frontend/src/components/Chat/chatContainer.test.tsx`

**Interfaces:**
- `SSEToolEvent` represents a bounded tool lifecycle record.
- `StreamCallbacks.onToolStart/onToolEnd/onToolError` receive typed tool events.
- Assistant `Message.tool_calls` carries live and persisted execution summaries.

- [ ] **Step 1: Add failing parser/render tests for tool SSE events and an assistant bubble trace.**
- [ ] **Step 2: Run the focused Vitest tests and confirm failure.**
- [ ] **Step 3: Implement typed SSE callbacks and assistant-side expandable tool trace rendering.**
- [ ] **Step 4: Redesign Agent chat CSS around the control-room direction, then run focused tests and the frontend build.**

### Task 3: Dashboard tool observability

**Files:**
- Modify: `app/schemas/audit.py`
- Modify: `app/services/audit.py`
- Modify: `frontend/src/types/api.ts`
- Modify: `frontend/src/pages/Dashboard/index.tsx`
- Create: `frontend/src/pages/Dashboard/Dashboard.css`
- Test: `tests/test_audit_dashboard.py`

**Interfaces:**
- `DashboardOut` gains `tool_calls_30d`, `tool_success_rate_30d`, `top_tools`, and `recent_tool_calls`.
- `AuditService.dashboard()` aggregates assistant message tool summaries from the last 30 days.

- [ ] **Step 1: Add failing dashboard aggregation tests.**
- [ ] **Step 2: Run the focused test and confirm the new fields are absent.**
- [ ] **Step 3: Implement bounded aggregation and response schema fields.**
- [ ] **Step 4: Add dashboard cards, tool ranking, and recent activity UI using the same visual language.**
- [ ] **Step 5: Run backend and frontend validation.**

### Self-review

- Knowledge defaulting is covered by Task 1 and is constrained to tenant-owned, non-deleted, indexed knowledge bases.
- Live tool visibility is covered by Task 2, including running/success/error states and assistant bubbles.
- Dashboard observability is covered by Task 3 using persisted summaries, without changing the existing API permission model.
- No new migration is required because `messages.tool_calls` already exists and is exposed by `MessageResponse`.
