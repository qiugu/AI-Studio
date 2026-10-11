// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import AgentForm from './AgentForm'

const { getToolCatalogMock, listModelsMock, navigateMock } = vi.hoisted(() => ({
  getToolCatalogMock: vi.fn(),
  listModelsMock: vi.fn(),
  navigateMock: vi.fn(),
}))

vi.mock('@/api/agent', () => ({
  getToolCatalog: getToolCatalogMock,
  createAgent: vi.fn(),
  updateAgent: vi.fn(),
  getAgent: vi.fn(),
}))

vi.mock('@/api/ai-model', () => ({
  listModels: listModelsMock,
}))

vi.mock('react-router-dom', () => ({
  useNavigate: () => navigateMock,
  useParams: () => ({}),
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
  getToolCatalogMock.mockResolvedValue({ data: [] })
  listModelsMock.mockResolvedValue({ data: { items: [] } })
})

afterEach(cleanup)

describe('Agent plugin capability experience', () => {
  it('解释插件能力，并从空状态直接前往添加插件', async () => {
    render(<AgentForm />)

    expect(await screen.findByText('给 Agent 添加插件能力')).toBeTruthy()
    expect(screen.getByText('还没有可添加的插件能力')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '去添加插件' }))
    expect(navigateMock).toHaveBeenCalledWith('/plugins')
  })
})
