# Sidebar Navigation Consistency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the left navigation use one hierarchy rule and keep the correct section expanded and selected on list, create, detail, edit, chat, execute, and configuration routes.

**Architecture:** Move navigation metadata and route-to-menu resolution into a pure TypeScript module. `Sidebar` renders the filtered metadata, controls `openKeys`, and derives the selected resource entry from the current pathname; unmatched routes leave the user's current expansion state unchanged.

**Tech Stack:** React 19, TypeScript 6, React Router 7, Ant Design 6, Vitest 5.

## Global Constraints

- Keep the current visual language; this change is information architecture and state behavior, not a redesign.
- Keep the dashboard as the only first-level destination because it is the tenant-wide home.
- Put stable resource destinations at level two under functional groups.
- Do not add create, detail, edit, chat, execute, or configuration pages as menu entries; map them to their stable resource entry.
- Preserve all unrelated uncommitted workspace changes.

---

### Task 1: Navigation metadata and route resolution

**Files:**
- Create: `frontend/src/components/Layout/navigation.ts`
- Create: `frontend/src/components/Layout/navigation.test.ts`

**Interfaces:**
- Produces: `getNavigationItems(audience: NavigationAudience): NavigationItem[]`
- Produces: `resolveNavigationState(pathname: string, items: NavigationItem[]): NavigationState`
- Produces: `keepActiveGroupOpen(openKeys: string[], activeGroupKey?: string): string[]`

- [x] **Step 1: Write the failing tests**

```ts
it('maps contextual routes to their stable resource entry', () => {
  const items = getNavigationItems('tenant-admin')
  expect(resolveNavigationState('/workflows/abc/execute', items)).toEqual({
    selectedKey: '/workflows',
    activeGroupKey: 'apps-group',
  })
})

it('keeps current expansion when a route has no menu entry', () => {
  expect(keepActiveGroupOpen(['resources-group'], undefined)).toEqual(['resources-group'])
})
```

- [x] **Step 2: Run tests and verify RED**

Run: `cd frontend && npm test -- src/components/Layout/navigation.test.ts`

Expected: FAIL because `navigation.ts` does not exist.

- [x] **Step 3: Implement the metadata and pure helpers**

Create grouped navigation for `tenant-member`, `tenant-admin`, and `platform-admin`. Match a route when it equals a leaf key or starts with `${key}/`, choosing the longest visible key so nested routes select their owning resource.

- [x] **Step 4: Run tests and verify GREEN**

Run: `cd frontend && npm test -- src/components/Layout/navigation.test.ts`

Expected: all navigation tests pass.

### Task 2: Controlled sidebar selection and expansion

**Files:**
- Modify: `frontend/src/components/Layout/Sidebar.tsx`
- Test: `frontend/src/components/Layout/navigation.test.ts`

**Interfaces:**
- Consumes: `getNavigationItems`, `resolveNavigationState`, and `keepActiveGroupOpen` from Task 1.
- Produces: an Ant Design `Menu` whose `selectedKeys` uses the resolved stable resource key and whose `openKeys` survives contextual or unmatched route changes and temporary sider collapse.

- [x] **Step 1: Add a failing helper test for opening the active group once**

```ts
it('opens the active group without discarding other expanded groups', () => {
  expect(keepActiveGroupOpen(['system-group'], 'apps-group')).toEqual([
    'system-group',
    'apps-group',
  ])
})
```

- [x] **Step 2: Run the test and verify RED**

Run: `cd frontend && npm test -- src/components/Layout/navigation.test.ts`

Expected: FAIL until the helper preserves existing keys and appends the active group.

- [x] **Step 3: Wire controlled state into `Sidebar`**

Use `useState` for remembered open groups, `useEffect` to append the active route's group, `selectedKeys` from `resolveNavigationState`, and ignore collapse-triggered empty `onOpenChange` updates while the sider is collapsed. Render icons only on first-level destinations/groups so all second-level entries have the same visual treatment.

- [ ] **Step 4: Verify tests, lint, and production build**

Run: `cd frontend && npm test -- src/components/Layout/navigation.test.ts`

Expected: PASS.

Run: `cd frontend && npm run lint`

Expected: exit code 0.

Run: `cd frontend && npm run build`

Expected: exit code 0 and a successful Vite production build.

Verification note: the navigation test suite and targeted lint pass. The full test suite and
production build are currently blocked by pre-existing `PluginConfig.tsx` work (`sourceMeta` is
undefined and several imports are unused); full-project lint also reports unrelated legacy errors.
