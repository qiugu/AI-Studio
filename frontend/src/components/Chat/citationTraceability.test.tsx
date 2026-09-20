// @vitest-environment jsdom
/**
 * 引用溯源的渲染层回归测试（Phase 2）。
 *
 * 覆盖链路：`Message.citations` → `MarkdownRenderer` AST 插件 → `CitationBadge`
 * → `CitationPanel`。AST 的边界条件（代码块免疫、链接内不嵌套）在
 * `utils/remarkCitations.test.ts` 里已单测，这里只验证「用户实际看到什么」。
 */
import { afterEach, describe, expect, it } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import MessageBubble from './MessageBubble'
import type { Citation, Message } from '@/types/agent'

// vitest 未开启 globals，RTL 的自动 cleanup 不会注册；antd Drawer 挂在 body 上的
// 节点会跨用例累积，导致后续查询命中多个元素。这里显式清理。
afterEach(cleanup)

function citation(partial: Partial<Citation> & Pick<Citation, 'marker'>): Citation {
  return {
    chunk_id: `chunk-${partial.marker}`,
    doc_id: 'doc-1',
    doc_name: '员工手册.pdf',
    source_page: 37,
    source_page_end: 38,
    heading_path: '3.2 休假',
    score: 0.8731,
    content: `原文片段 ${partial.marker}`,
    ...partial,
  }
}

function assistantMessage(content: string, citations?: Citation[] | null): Message {
  return {
    id: 'm1',
    conversation_id: 'c1',
    tenant_id: 't1',
    role: 'assistant',
    content,
    prompt_tokens: 0,
    completion_tokens: 0,
    total_tokens: 0,
    tool_calls: null,
    tool_call_id: null,
    tool_name: null,
    created_at: '2026-09-16T00:00:00Z',
    ...(citations === undefined ? {} : { citations }),
  }
}

describe('MessageBubble 引用角标', () => {
  it('有引用时 [n] 渲染为可点击角标，点击后抽屉展示来源与原文', () => {
    render(
      <MessageBubble
        message={assistantMessage('依据 [1] 条规定。', [citation({ marker: 1 })])}
      />
    )

    const badge = screen.getByRole('button', { name: /查看引用 1/ })
    expect(badge.textContent).toBe('[1]')

    fireEvent.click(badge)

    // 抽屉里同时出现文档名、出处与原文快照
    expect(screen.getByText('员工手册.pdf')).toBeTruthy()
    expect(screen.getByText('第 37–38 页 · §3.2 休假')).toBeTruthy()
    expect(screen.getByText('原文片段 1')).toBeTruthy()
  })

  it('无引用时正文里的 [1] 保持字面文本，不被点亮', () => {
    const { container } = render(<MessageBubble message={assistantMessage('数组下标 [1]。')} />)

    expect(screen.queryByRole('button', { name: /查看引用/ })).toBeNull()
    expect(container.textContent).toContain('数组下标 [1]。')
  })

  it('代码块里的 [1] 不会被当成角标', () => {
    render(
      <MessageBubble
        message={assistantMessage('```ts\nconst x = arr[1]\n```', [citation({ marker: 1 })])}
      />
    )

    expect(screen.queryByRole('button', { name: /查看引用 1/ })).toBeNull()
  })

  it('模型编造的编号不渲染成角标，避免看起来像已溯源', () => {
    const { container } = render(
      <MessageBubble
        message={assistantMessage('见 [9]，但只有 [1] 有来源。', [citation({ marker: 1 })])}
      />
    )

    // 只有 marker=1 是角标；marker=9 无来源，退回纯文本
    expect(screen.getAllByRole('button', { name: /查看引用/ })).toHaveLength(1)
    expect(container.querySelectorAll('.citation-badge')).toHaveLength(1)
    expect(container.textContent).toContain('[9]')
  })

  it('点击角标后关闭抽屉，再次点击可重新打开', () => {
    render(<MessageBubble message={assistantMessage('依据 [1]。', [citation({ marker: 1 })])} />)

    const badge = screen.getByRole('button', { name: /查看引用 1/ })
    fireEvent.click(badge)
    expect(screen.getByText('原文片段 1')).toBeTruthy()

    // Drawer 的关闭按钮（aria-label 由 antd 提供）
    const closeButton = document.querySelector('.ant-drawer-close')
    expect(closeButton).toBeTruthy()
    fireEvent.click(closeButton as Element)

    fireEvent.click(badge)
    expect(screen.getByText('原文片段 1')).toBeTruthy()
  })
})
