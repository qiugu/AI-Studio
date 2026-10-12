// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

import { useAuthStore } from '@/stores/auth'
import KnowledgeList from './KnowledgeList'

const { createKnowledgeBaseMock, listKnowledgeBasesMock } = vi.hoisted(() => ({
  createKnowledgeBaseMock: vi.fn(),
  listKnowledgeBasesMock: vi.fn(),
}))

vi.mock('@/api/knowledge', () => ({
  createKnowledgeBase: createKnowledgeBaseMock,
  listKnowledgeBases: listKnowledgeBasesMock,
  updateKnowledgeBase: vi.fn(),
  deleteKnowledgeBase: vi.fn(),
}))

vi.mock('react-router-dom', () => ({
  useNavigate: () => vi.fn(),
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
      roles: [{
        id: 'role-1',
        tenant_id: 'tenant-1',
        name: 'Tenant admin',
        code: 'tenant_admin',
        status: true,
        is_admin: true,
        permissions: [],
      }],
    },
  })
  listKnowledgeBasesMock.mockResolvedValue({
    data: { items: [], total: 0, page: 1, page_size: 20 },
  })
  createKnowledgeBaseMock.mockResolvedValue({ data: {} })
})

afterEach(cleanup)

describe('KnowledgeList', () => {
  it('创建知识库时由服务端选择已部署的 Embedding 模型', async () => {
    render(<KnowledgeList />)

    fireEvent.click(await screen.findByRole('button', { name: '创建知识库' }))
    fireEvent.change(screen.getByLabelText('知识库名称'), {
      target: { value: '运维手册' },
    })
    fireEvent.click(screen.getByRole('button', { name: /确\s*定/ }))

    await waitFor(() => {
      expect(createKnowledgeBaseMock).toHaveBeenCalledWith({
        name: '运维手册',
        description: undefined,
      })
    })
  })
})
