// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import Users from './Users'

const {
  listUsersMock,
  listRolesMock,
  updateUserMock,
} = vi.hoisted(() => ({
  listUsersMock: vi.fn(),
  listRolesMock: vi.fn(),
  updateUserMock: vi.fn(),
}))

vi.mock('@/api/user', () => ({
  listUsers: listUsersMock,
  updateUser: updateUserMock,
  createUser: vi.fn(),
  deleteUser: vi.fn(),
}))

vi.mock('@/api/role', () => ({
  listRoles: listRolesMock,
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
  listUsersMock.mockResolvedValue({
    data: {
      items: [{
        id: 'user-1',
        tenant_id: 'tenant-1',
        email: 'member@example.com',
        nickname: '成员',
        avatar: null,
        status: true,
        is_platform_admin: false,
        email_verified: true,
        is_tenant_owner: false,
        last_login_at: null,
        created_at: null,
        updated_at: null,
        roles: [],
      }],
      total: 1,
      page: 1,
      page_size: 200,
    },
  })
  listRolesMock.mockResolvedValue({
    data: {
      items: [{
        id: 'role-1',
        tenant_id: 'tenant-1',
        name: '运营人员',
        code: 'operator',
        description: null,
        status: true,
        is_admin: false,
        permissions: [],
      }],
      total: 1,
      page: 1,
      page_size: 200,
    },
  })
})

afterEach(cleanup)

describe('Users security boundaries', () => {
  it('编辑成员时不提供密码和昵称输入框', async () => {
    render(<Users />)

    fireEvent.click(await screen.findByRole('button', { name: '编辑' }))

    expect(screen.queryByLabelText('密码')).toBeNull()
    expect(screen.queryByLabelText('昵称')).toBeNull()
    expect(screen.queryByPlaceholderText('仅修改状态时需要')).toBeNull()
    expect(screen.queryByText(/用户 ID 和邮箱是审计追踪依据/)).toBeNull()
    expect(screen.queryByRole('button', { name: '发起密码重置' })).toBeNull()
    expect(screen.getByText('选择角色')).toBeTruthy()
    expect(screen.queryByRole('button', { name: '管理角色' })).toBeNull()
  })
})
