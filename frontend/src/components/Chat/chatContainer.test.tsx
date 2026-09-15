// @vitest-environment jsdom
/**
 * ChatContainer / MessageBubble 的错误消息渲染回归测试。
 *
 * 修复的缺陷（2026-09-15）：`ChatContainer` 曾把所有 `is_error` 消息从消息数组里
 * **过滤出来**、统一渲染成 Alert 放在滚动容器**顶部**。后果是错误与发生位置脱节，
 * 长会话滚动到底时错误甚至不在视口内；而 `MessageBubble` 里本就写好了
 * `message-content.error` 分支，属于从未被走到的死代码。
 */
import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import ChatContainer from './ChatContainer'
import type { Message } from '@/types/agent'

function msg(partial: Partial<Message> & Pick<Message, 'id' | 'role' | 'content'>): Message {
  return {
    conversation_id: 'c1',
    tenant_id: 't1',
    prompt_tokens: 0,
    completion_tokens: 0,
    total_tokens: 0,
    tool_calls: null,
    tool_call_id: null,
    tool_name: null,
    created_at: '2026-09-15T00:00:00Z',
    ...partial,
  }
}

/** 取渲染结果里所有消息的文本顺序（按 DOM 出现次序）。 */
function renderedOrder(container: HTMLElement): string[] {
  return Array.from(container.querySelectorAll('.message-wrapper')).map(
    (el) => el.textContent ?? ''
  )
}

describe('ChatContainer 错误消息渲染位置', () => {
  const messages: Message[] = [
    msg({ id: '1', role: 'user', content: '帮我搜一下 AI-Studio' }),
    msg({
      id: '2',
      role: 'assistant',
      content: '智能体执行失败：工具调用智能体装配失败',
      is_error: true,
      error_code: 'AGENT_ASSEMBLY_ERROR',
    }),
    msg({ id: '3', role: 'user', content: '再试一次' }),
  ]

  it('错误消息保持在发生位置，不被提到会话顶部', () => {
    const { container } = render(<ChatContainer messages={messages} />)
    const order = renderedOrder(container)

    expect(order).toHaveLength(3)
    // 关键断言：第一条必须是用户提问，而不是错误
    expect(order[0]).toContain('帮我搜一下 AI-Studio')
    // 错误位于第 2 位（原位置），不是第 1 位
    expect(order[1]).toContain('智能体执行失败')
    // 错误之后的消息也保持在其后
    expect(order[2]).toContain('再试一次')
  })

  it('错误用消息气泡内联渲染（而非置顶 Alert）', () => {
    const { container } = render(<ChatContainer messages={messages} />)
    expect(container.querySelectorAll('.message-content.error')).toHaveLength(1)
    // antd Alert 的置顶容器已移除
    expect(container.querySelector('.ant-alert')).toBeNull()
  })

  it('标题按 error_code 映射，不再一律「模型调用失败」', () => {
    render(
      <ChatContainer
        messages={[
          msg({
            id: 'e1',
            role: 'assistant',
            content: 'API认证失败，请检查API密钥是否有效',
            is_error: true,
            error_code: 'AUTHENTICATION_ERROR',
          }),
        ]}
      />
    )
    expect(screen.getByText('API 认证失败')).toBeTruthy()
    expect(screen.queryByText('模型调用失败')).toBeNull()
  })

  it('未知 error_code 退化到中性标题', () => {
    render(
      <ChatContainer
        messages={[
          msg({ id: 'e2', role: 'assistant', content: '出了点问题', is_error: true }),
        ]}
      />
    )
    expect(screen.getByText('执行失败')).toBeTruthy()
  })
})
