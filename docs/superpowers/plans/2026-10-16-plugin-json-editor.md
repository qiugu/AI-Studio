# 插件 JSON 编辑器优化实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将插件配置页中所有需要输入 JSON 的文本框统一替换为带 JSON 语法高亮、格式化、示例填充和实时错误提示的编辑器。

**Architecture:** 新增轻量 `JsonEditor` 包装组件，复用现有 Monaco `CodeEditor`，只负责 JSON 编辑体验、格式化和语法状态展示；插件配置页继续保留现有字符串状态与保存解析逻辑，把连接请求头、连接高级配置、端点高级字段、试用参数及 Schema 字段接入该组件。只对输入场景改造，测试结果只读输出不改变。

**Tech Stack:** React 19、TypeScript、Ant Design、`@monaco-editor/react`、Vitest、Testing Library。

## Global Constraints

- 遵循 `CLAUDE.md`：前端类型安全，现有 API 载荷和插件配置保存语义不变。
- JSON 必须使用标准 JSON 语法；空输入仅在现有字段允许为空时允许保存。
- 不新增编辑器依赖，复用项目已有的 `CodeEditor` / Monaco。
- 编辑器必须保留可见键盘焦点、移动端可用和错误信息，不依赖 Monaco 在 jsdom 中运行。

---

### Task 1: 定义 JSON 编辑器行为并写失败测试

**Files:**
- Create: `frontend/src/components/JsonEditor.test.tsx`
- Create: `frontend/src/components/JsonEditor.tsx`

**Interfaces:**
- Consumes: `value?: string`、`onChange?: (value: string) => void`、`label`、`tooltip`、`placeholder`、`example`、`height`、`required`、`allowEmpty`。
- Produces: 可受控的 JSON 编辑器，调用 `CodeEditor` 时固定 `language="json"`，提供“格式化”“填入示例”操作，并在 JSON 无效时展示错误。

- [x] **Step 1: Write the failing test**

测试覆盖三个独立行为：编辑器使用 JSON 语言；合法 JSON 可格式化并回调格式化文本；非法 JSON 展示语法错误而不抛异常；示例按钮能写入示例。

```tsx
// @vitest-environment jsdom
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import JsonEditor from './JsonEditor'

const codeEditorMock = vi.fn(({ value, onChange }: { value: string; onChange?: (value: string) => void }) => (
  <textarea aria-label="json-code-editor" value={value} onChange={(event) => onChange?.(event.target.value)} />
))

vi.mock('./CodeEditor', () => ({
  default: (props: { value: string; onChange?: (value: string) => void; language?: string }) => {
    codeEditorMock(props)
    return <textarea aria-label="json-code-editor" value={props.value} onChange={(event) => props.onChange?.(event.target.value)} />
  },
}))

describe('JsonEditor', () => {
  it('uses Monaco JSON mode and formats valid JSON', () => {
    const onChange = vi.fn()
    render(<JsonEditor label="高级配置" value='{"region":"cn-east"}' onChange={onChange} />)

    expect(codeEditorMock).toHaveBeenCalledWith(expect.objectContaining({ language: 'json' }))
    fireEvent.click(screen.getByRole('button', { name: '格式化 JSON' }))

    expect(onChange).toHaveBeenCalledWith('{\n  "region": "cn-east"\n}')
  })

  it('shows a validation error for invalid JSON and fills an example on request', () => {
    const onChange = vi.fn()
    render(<JsonEditor label="请求体" value='{"query":}' example='{\n  "query": "北京天气"\n}' onChange={onChange} />)

    expect(screen.getByText(/JSON 语法错误/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '填入示例' }))
    expect(onChange).toHaveBeenCalledWith('{\n  "query": "北京天气"\n}')
  })
})
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- src/components/JsonEditor.test.tsx`

Expected: FAIL because `frontend/src/components/JsonEditor.tsx` does not exist yet.

- [x] **Step 3: Write minimal implementation**

实现受控编辑器：调用 `CodeEditor` 时传 `language="json"`；使用 `JSON.parse` 实时计算错误；格式化成功时使用 `JSON.stringify(parsed, null, 2)`；格式化失败时保持原文并显示错误；示例按钮只在提供示例时显示。

- [x] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test -- src/components/JsonEditor.test.tsx`

Expected: PASS。

### Task 2: 接入插件配置页的全部 JSON 输入场景

**Files:**
- Modify: `frontend/src/pages/Plugins/PluginConfig.tsx`
- Modify: `frontend/src/pages/Plugins/PluginExperience.css`
- Modify: `frontend/src/pages/Plugins/PluginConfig.test.tsx`

**Interfaces:**
- Consumes: Task 1 的 `JsonEditor`。
- Produces: 插件配置页中连接请求头、Schema 配置、连接高级配置、端点高级字段、试用参数均使用 JSON 编辑器；保存和校验 API 行为保持兼容。

- [x] **Step 1: Write the failing integration assertions**

在 `PluginConfig.test.tsx` 中 mock `@/components/JsonEditor` 为可识别的 `<textarea>`，并增加断言：无 Schema 页面显示 `附加请求头` 的 JSON 编辑器；页面渲染后出现多个 JSON 编辑器；不再依赖 `plugin-code-field` 的普通 TextArea。

- [x] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- src/pages/Plugins/PluginConfig.test.tsx`

Expected: FAIL because the page still renders `Input.TextArea` for at least the connection headers field and does not mount `JsonEditor` there.

- [x] **Step 3: Write minimal implementation**

导入 `JsonEditor`；删除页面内重复的 `JsonField` 实现，改为基于 `JsonEditor` 的 `Form.Item`；将 object/array Schema 字段改成 `JsonEditor`；保留现有 `parseJsonField` 作为保存时的最终校验，并确保 `value` 为空时不传 `undefined` 给编辑器。为编辑器增加紧凑边框、工具栏和错误状态样式，沿用插件页的 teal 视觉变量。

- [x] **Step 4: Run focused tests and type-check**

Run: `cd frontend && npm test -- src/components/JsonEditor.test.tsx src/pages/Plugins/PluginConfig.test.tsx`

Then run: `cd frontend && npm run build`

Expected: focused tests PASS and TypeScript/Vite build PASS。

### Task 3: 回归验证与整理

**Files:**
- Modify: `frontend/src/components/JsonEditor.tsx` only if review finds accessibility or responsive issues.
- Modify: `frontend/src/pages/Plugins/PluginExperience.css` only if the focused visual styles need correction.

- [x] **Step 1: Run the complete frontend test suite**

Run: `cd frontend && npm test`

Expected: all existing tests and new JSON editor tests PASS。

- [x] **Step 2: Run lint**

Run: `cd frontend && npm run lint`

Expected: ESLint exits with code 0。

- [x] **Step 3: Review changed files**

Run: `git diff --check && git diff --stat && git status --short`

Expected: no whitespace errors; only the JSON editor, plugin page/styles, tests, and plan are changed。
