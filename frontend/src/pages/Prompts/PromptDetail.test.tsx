// @vitest-environment jsdom
//
// PromptDetail 版本历史的交互回归测试。
//
// 背景（真实故障 + 设计结论）：
// 1) 曾有一个「查看」按钮，作用只是把下方常驻的「版本内容」卡片换一版；当 prompt
//    只有一个版本时点击必然零变化，被误认为按钮失效。
// 2) 结论是删掉该按钮，改为「点击版本行即预览」——选中态由行高亮 + 「预览中」标签表达。
// 本测试锁定这一契约，防止「查看」按钮被重新引入。
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

import type { PromptVersion } from '@/types/prompt'
import PromptDetail from './PromptDetail'

const PROMPT_ID = 'd0ac65cd-35d3-4bd4-8ad3-d3505940ad6b'

const v1: PromptVersion = {
  id: 'version-1',
  prompt_id: PROMPT_ID,
  version_number: 1,
  content: 'content v1',
  variables: ['job_desc'],
  is_current: true,
  created_by: null,
  created_at: '2026-09-13T10:00:00',
}

const v2: PromptVersion = {
  ...v1,
  id: 'version-2',
  version_number: 2,
  content: 'content v2',
  is_current: false,
}

const { getPromptMock, listVersionsMock, activateVersionMock, testPromptMock, listModelsMock } =
  vi.hoisted(() => ({
    getPromptMock: vi.fn(),
    listVersionsMock: vi.fn(),
    activateVersionMock: vi.fn(),
    testPromptMock: vi.fn(),
    listModelsMock: vi.fn(),
  }))

vi.mock('@/api/prompt', () => ({
  getPrompt: getPromptMock,
  listVersions: listVersionsMock,
  activateVersion: activateVersionMock,
  testPrompt: testPromptMock,
}))

vi.mock('@/api/ai-model', () => ({ listModels: listModelsMock }))

vi.mock('antd', async (importOriginal) => {
  const actual = await importOriginal<typeof import('antd')>()
  return {
    ...actual,
    message: { success: vi.fn(), info: vi.fn(), error: vi.fn(), warning: vi.fn() },
  }
})

// monaco 在 jsdom 中无法加载，用轻量替身暴露预览内容
vi.mock('@/components/CodeEditor', () => ({
  default: ({ value }: { value: string }) => <pre data-testid="preview-content">{value}</pre>,
}))

/** 定位包含指定版本号的行。 */
function findVersionRow(label: string): HTMLElement {
  const row = screen
    .getAllByRole('row')
    .find((r) => within(r).queryByText(label))
  if (!row) throw new Error(`未找到版本行: ${label}`)
  return row
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={[`/prompts/${PROMPT_ID}`]}>
      <Routes>
        <Route path="/prompts/:id" element={<PromptDetail />} />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()

  // jsdom 缺失的浏览器 API（antd Table / 滚动定位需要）
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }),
  })
  window.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver
  Element.prototype.scrollIntoView = vi.fn()

  getPromptMock.mockResolvedValue({
    data: {
      id: PROMPT_ID,
      tenant_id: '1',
      name: '旅游规划',
      description: null,
      category: null,
      tags: null,
      status: 'draft',
      created_by: null,
      created_at: null,
      updated_at: null,
      current_version: v1,
    },
  })
  listModelsMock.mockResolvedValue({ data: { items: [] } })
  activateVersionMock.mockResolvedValue({ data: v2 })
  testPromptMock.mockResolvedValue({ data: null })
})

afterEach(() => {
  cleanup()
})

describe('PromptDetail 版本历史交互', () => {
  it('默认预览当前版本，并在对应行标记「预览中」', async () => {
    listVersionsMock.mockResolvedValue({ data: [v2, v1] })
    renderPage()

    await waitFor(() => expect(screen.getByTestId('preview-content')).toBeDefined())

    expect(screen.getByTestId('preview-content').textContent).toBe('content v1')
    // 选中态只由行底色表达，不再有「预览中」标签（同一事实不重复表述）
    expect(screen.queryByText('预览中')).toBeNull()
  })

  it('点击其他版本行即切换预览内容，测试面板同步跟随', async () => {
    listVersionsMock.mockResolvedValue({ data: [v2, v1] })
    renderPage()
    await waitFor(() => expect(screen.getByTestId('preview-content')).toBeDefined())
    expect(screen.getByText('测试版本：v1')).toBeDefined()

    fireEvent.click(findVersionRow('v2'))

    await waitFor(() => expect(screen.getByTestId('preview-content').textContent).toBe('content v2'))
    // 选中态＝行底色（「预览中」标签已移除，同一事实不重复表述）
    expect(findVersionRow('v2').getAttribute('style')).toContain('background')
    expect(findVersionRow('v1').getAttribute('style')).not.toContain('background')
    expect(screen.getByText('测试版本：v2')).toBeDefined()
  })

  it('重复点击已在预览的行不会静默无反应（仍有滚动定位反馈）', async () => {
    listVersionsMock.mockResolvedValue({ data: [v2, v1] })
    renderPage()
    await waitFor(() => expect(screen.getByTestId('preview-content')).toBeDefined())

    fireEvent.click(findVersionRow('v1'))

    // 状态无需变化，但每次点击都应把预览区带入视野，让操作有可见结果
    await waitFor(() => expect(Element.prototype.scrollIntoView).toHaveBeenCalled())
    expect(screen.getByTestId('preview-content').textContent).toBe('content v1')
  })

  it('版本行不再渲染「查看」按钮，「操作」列只承载真实的「激活」写操作', async () => {
    listVersionsMock.mockResolvedValue({ data: [v2, v1] })
    renderPage()
    await waitFor(() => expect(screen.getByTestId('preview-content')).toBeDefined())

    expect(within(findVersionRow('v1')).queryByRole('button', { name: /查\s*看/ })).toBeNull()
    expect(within(findVersionRow('v2')).queryByRole('button', { name: /查\s*看/ })).toBeNull()

    expect(within(findVersionRow('v2')).getByRole('button', { name: /激\s*活/ })).toBeDefined()
    // 当前版本行无可执行操作：留空单元格，不再用「—」占位
    expect(within(findVersionRow('v1')).queryByRole('button')).toBeNull()
  })

  it('只有一个版本时不渲染「操作」列（无可操作项，不白占一列）', async () => {
    listVersionsMock.mockResolvedValue({ data: [v1] })
    renderPage()
    await waitFor(() => expect(screen.getByTestId('preview-content')).toBeDefined())

    expect(screen.queryByText('操作')).toBeNull()
    // 其余列不受影响
    expect(screen.getByText('版本')).toBeDefined()
    expect(screen.getByText('创建时间')).toBeDefined()
  })

  it('存在历史版本时才渲染「操作」列', async () => {
    listVersionsMock.mockResolvedValue({ data: [v2, v1] })
    renderPage()
    await waitFor(() => expect(screen.getByTestId('preview-content')).toBeDefined())

    expect(screen.getByText('操作')).toBeDefined()
  })

  it('点击「激活」只触发一次激活请求（行点击事件已被阻止冒泡）', async () => {
    listVersionsMock.mockResolvedValue({ data: [v2, v1] })
    renderPage()
    await waitFor(() => expect(screen.getByTestId('preview-content')).toBeDefined())

    fireEvent.click(within(findVersionRow('v2')).getByRole('button', { name: /激\s*活/ }))

    await waitFor(() => expect(activateVersionMock).toHaveBeenCalledTimes(1))
    expect(activateVersionMock).toHaveBeenCalledWith(PROMPT_ID, 'version-2')
  })
})
