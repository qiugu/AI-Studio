// @vitest-environment jsdom
import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import ChatInput from './ChatInput'

describe('ChatInput', () => {
  it('exposes the composer purpose and keyboard shortcut', () => {
    render(<ChatInput onSend={vi.fn()} />)

    expect(screen.getByRole('textbox', { name: '消息输入框' })).toBeTruthy()
    expect(screen.getByText('Ctrl / ⌘ + Enter 发送')).toBeTruthy()
  })
})
