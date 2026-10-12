# Sidebar Navigation Consistency Implementation Plan

**Goal:** Keep all stable navigation entries visible at one level while ensuring contextual routes still highlight their owning list entry.

**Architecture:** Store one flat, permission-filtered navigation definition. List and create routes are explicit menu entries; detail, edit, chat, configuration, and execute routes are resolved to the longest matching visible prefix. There are no nested menu groups, so a route outside the menu cannot collapse an expanded submenu.

**Tech Stack:** React 19, TypeScript 6, React Router 7, Ant Design 6, Vitest 5.

## Navigation standard

- Every stable list or create route is a direct sidebar entry.
- Dynamic resource routes map to their list entry (`/agents/:id/chat` → `/agents`).
- Visibility is filtered by tenant member, tenant administrator, or platform administrator audience.
- The sidebar keeps the existing visual language and icon treatment without adding another navigation depth.

## Implementation

### Task 1: Flat navigation metadata and route resolution

**Files:**
- Create: `frontend/src/components/Layout/navigation.ts`
- Test: `frontend/src/components/Layout/navigation.test.ts`

- [x] Define direct entries for dashboard, provider/model/prompt/agent/workflow creation, stable lists, knowledge, plugins, system pages, and platform tenant creation.
- [x] Filter those entries by audience.
- [x] Resolve the longest matching route prefix so dynamic pages select the correct list or create entry.
- [x] Normalize trailing slashes and return no selection for unknown routes.

### Task 2: Sidebar integration

**Files:**
- Modify: `frontend/src/components/Layout/Sidebar.tsx`

- [x] Render the flat entries as Ant Design inline menu items.
- [x] Drive `selectedKeys` from the route resolver.
- [x] Keep permission-based visibility for tenant members, tenant administrators, and platform administrators.
- [x] Remove the extra submenu state because the menu intentionally has one visible level.

## Verification

- `cd frontend && npm test -- src/components/Layout/navigation.test.ts` — 16 tests pass.
- `cd frontend && npx eslint src/components/Layout/Sidebar.tsx src/components/Layout/navigation.ts src/components/Layout/navigation.test.ts` — passes.
- Full-project build/test status remains subject to unrelated existing `PluginConfig.tsx` errors.
