# Plugin Experience Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把插件管理从面向协议的配置后台改成面向结果的“Agent 能力中心”，让租户管理员看懂插件的作用并完成连接、试用和授权。

**Architecture:** 保留现有后端接口和数据模型，只重组前端信息架构、文案和展示组件。新增一组纯函数处理完成状态与普通连接字段，以单元测试锁定行为；插件列表、配置页和 Agent 授权页共用一套视觉语言和用户词汇。

**Tech Stack:** React 19, TypeScript 6, Ant Design 6, Vitest, Testing Library, CSS

## Global Constraints

- 不改变插件 API、租户隔离、敏感配置和 Agent 端点级授权语义。
- 主流程使用“插件、能力、连接、试用、给 Agent 使用”等用户语言。
- OpenAPI、JSON Schema、HTTP 方法与路径只出现在高级设置或辅助信息中。
- 当前仅可运行 HTTP 插件；不可用的 MCP / Skill 不进入主流程。
- 保留并尊重工作区已有未提交改动。

---

### Task 1: Experience model and regression tests

**Files:**
- Create: `frontend/src/pages/Plugins/pluginExperience.ts`
- Create: `frontend/src/pages/Plugins/pluginExperience.test.ts`

**Interfaces:**
- Produces: `getPluginReadiness(plugin)`, `getSetupProgress(input)`, `splitConnectionConfig(items)`, `buildConnectionConfigItems(input)`.
- Consumes: existing `Plugin` and `PluginConfigItem` types.

- [ ] **Step 1: Write failing tests**

  Cover ready / needs-capability / paused labels, four-stage progress, common field extraction, preservation of advanced values, and retaining an existing secret when the field is left empty.

- [ ] **Step 2: Run test to verify it fails**

  Run: `npm test -- src/pages/Plugins/pluginExperience.test.ts`

  Expected: FAIL because `pluginExperience.ts` does not exist.

- [ ] **Step 3: Implement minimal pure helpers**

  Keep helpers independent from React so page components only render returned user-facing state.

- [ ] **Step 4: Run test to verify it passes**

  Run: `npm test -- src/pages/Plugins/pluginExperience.test.ts`

  Expected: PASS.

### Task 2: Plugin capability center

**Files:**
- Modify: `frontend/src/pages/Plugins/PluginList.tsx`
- Create: `frontend/src/pages/Plugins/PluginExperience.css`
- Create: `frontend/src/pages/Plugins/PluginList.test.tsx`

**Interfaces:**
- Consumes: `getPluginReadiness(plugin)` from Task 1.
- Produces: a capability-first list, actionable empty state, and an advanced-only service-definition section in the create/edit modal.

- [ ] **Step 1: Write failing UI tests**

  Assert the page says “让 Agent 连接你正在使用的服务”, calls the primary action “添加插件”, explains the three-part connection, and places service-definition JSON under “高级设置”.

- [ ] **Step 2: Run test to verify it fails**

  Run: `npm test -- src/pages/Plugins/PluginList.test.tsx`

  Expected: FAIL on missing capability-first copy.

- [ ] **Step 3: Build the capability center**

  Replace the dense table with responsive plugin cards. Each card shows purpose, available ability count, readiness, primary next action, and restrained secondary actions. Keep create/edit/delete/status behavior unchanged.

- [ ] **Step 4: Run tests and typecheck**

  Run: `npm test -- src/pages/Plugins/PluginList.test.tsx src/pages/Plugins/pluginExperience.test.ts`

  Expected: PASS.

### Task 3: Guided plugin setup and Agent activation

**Files:**
- Modify: `frontend/src/pages/Plugins/PluginConfig.tsx`
- Modify: `frontend/src/pages/Agents/AgentForm.tsx`
- Modify: `frontend/src/pages/Plugins/PluginExperience.css`
- Create: `frontend/src/pages/Plugins/PluginConfig.test.tsx`

**Interfaces:**
- Consumes: connection helpers and setup progress from Task 1.
- Produces: a four-stage guided setup, friendly basic connection fields, “可用能力” management, a plain-language test flow, and a direct route to Agent activation.

- [ ] **Step 1: Write failing UI tests**

  Assert the setup page exposes “连接服务 / 添加能力 / 试用一次 / 给 Agent 使用”, renders friendly default fields when no custom form exists, and offers “去 Agent 开启使用”.

- [ ] **Step 2: Run test to verify it fails**

  Run: `npm test -- src/pages/Plugins/PluginConfig.test.tsx`

  Expected: FAIL on the missing guided setup.

- [ ] **Step 3: Implement the guided setup**

  Preserve existing API calls and sensitive-value semantics. Move raw JSON and protocol terminology into collapsible advanced areas, present endpoint descriptions before technical method/path, and add clear next actions.

- [ ] **Step 4: Improve Agent authorization copy**

  Rename the section to “给 Agent 添加插件能力”, show human descriptions first, provide a direct empty-state action to the plugin center, and retain destructive-operation confirmation.

- [ ] **Step 5: Verify all affected frontend behavior**

  Run: `npm test -- src/pages/Plugins src/pages/Agents/agentToolBinding.test.ts`

  Run: `npm run build`

  Expected: all tests pass and production build succeeds.

### Task 4: Visual QA and restraint pass

**Files:**
- Modify if needed: `frontend/src/pages/Plugins/PluginExperience.css`

**Interfaces:**
- Consumes: completed pages from Tasks 2–3.
- Produces: responsive, keyboard-visible and reduced-motion-safe presentation.

- [ ] **Step 1: Inspect list, setup, and Agent form at desktop width**

  Confirm hierarchy, card density, progression, modal copy, and action naming.

- [ ] **Step 2: Inspect at narrow width**

  Confirm the capability rail stacks, cards remain readable, actions wrap, and no horizontal overflow is introduced.

- [ ] **Step 3: Remove one unnecessary decorative element**

  Preserve the capability rail as the single signature device; remove any other treatment that competes with it.

- [ ] **Step 4: Run final lint/build checks**

  Run: `npm run lint`

  Run: `npm run build`

  Expected: no errors introduced by the changed files.
