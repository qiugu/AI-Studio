// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'

const { changeMyPasswordMock, logoutMock } = vi.hoisted(() => ({
  changeMyPasswordMock: vi.fn(),
  logoutMock: vi.fn(),
}))

vi.mock('@/api/auth', () => ({
  changeMyPassword: changeMyPasswordMock,
}))

vi.mock('@/stores/app', () => ({
  useAppStore: (selector: (state: { sidebarCollapsed: boolean; toggleSidebar: () => void }) => unknown) =>
    selector({ sidebarCollapsed: false, toggleSidebar: vi.fn() }),
}))

vi.mock('@/stores/auth', () => ({
  useAuthStore: (selector: (state: { user: object; logout: () => Promise<void> }) => unknown) =>
    selector({
      user: { email: 'member@example.com', nickname: '成员', avatar: null },
      logout: logoutMock,
    }),
}))

import Header from './Header'

describe('Header account menu', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      value: () => ({
        matches: false,
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
    changeMyPasswordMock.mockResolvedValue({ data: { message: '密码已修改' } })
  })

  it('从右上角菜单修改当前用户自己的密码', async () => {
    render(
      <MemoryRouter>
        <Header />
      </MemoryRouter>,
    )

    fireEvent.click(screen.getByText('成员').closest('.ant-dropdown-trigger') as HTMLElement)
    fireEvent.click(await screen.findByText('修改密码'))
    fireEvent.change(screen.getByPlaceholderText('当前密码'), { target: { value: 'old-password' } })
    fireEvent.change(screen.getByPlaceholderText('至少 12 位'), { target: { value: 'new-password-123' } })
    fireEvent.change(screen.getByPlaceholderText('再次输入新密码'), { target: { value: 'new-password-123' } })
    fireEvent.click(screen.getByRole('button', { name: '保存密码' }))

    await waitFor(() => {
      expect(changeMyPasswordMock).toHaveBeenCalledWith('old-password', 'new-password-123')
    })
  })
})
