// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { useAuthStore } from '@/stores/auth'
import PluginList from './PluginList'

const { listPluginsMock, navigateMock } = vi.hoisted(() => ({
  listPluginsMock: vi.fn(),
  navigateMock: vi.fn(),
}))

vi.mock('@/api/plugin', () => ({
  listPlugins: listPluginsMock,
  createPlugin: vi.fn(),
  updatePlugin: vi.fn(),
  deletePlugin: vi.fn(),
  testPlugin: vi.fn(),
}))

vi.mock('react-router-dom', () => ({
  useNavigate: () => navigateMock,
}))

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

  useAuthStore.setState({
    user: {
      id: 'user-1',
      tenant_id: 'tenant-1',
      email: 'admin@example.com',
      nickname: 'Admin',
      avatar: null,
      status: true,
      is_platform_admin: false,
      email_verified: true,
      is_tenant_owner: false,
      last_login_at: null,
      created_at: null,
      updated_at: null,
      capabilities: ['tenant.roles_manage', 'plugin.read'],
      roles: [],
    },
  })
  listPluginsMock.mockResolvedValue({
    data: { items: [], total: 0, page: 1, page_size: 200 },
  })
})

afterEach(cleanup)

describe('PluginList capability-first experience', () => {
  it('先解释插件作用，再邀请用户添加能力', async () => {
    render(<PluginList />)

    expect(
      await screen.findByRole('heading', {
        name: '让 Agent 连接你正在使用的服务',
      })
    ).toBeTruthy()
    expect(screen.getByText('使用的服务').classList.contains('plugin-hero__nowrap')).toBe(true)
    expect(screen.getByText('你的服务')).toBeTruthy()
    expect(screen.getByText('插件')).toBeTruthy()
    expect(screen.getByText('Agent')).toBeTruthy()
    expect(screen.getByRole('button', { name: '添加插件' })).toBeTruthy()
  })

  it('把专业字段收进高级设置', async () => {
    render(<PluginList />)

    fireEvent.click(await screen.findByRole('button', { name: '添加插件' }))

    expect(screen.getByRole('dialog')).toBeTruthy()
    expect(screen.getByText('它能帮助 Agent 做什么？')).toBeTruthy()
    expect(screen.getByText('高级设置')).toBeTruthy()
    expect(screen.queryByText('接入方式（怎么接）')).toBeNull()
  })
})
