// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

import WorkflowExecution from './WorkflowExecution'

const {
  abortMock,
  createWorkflowStreamRequestMock,
  getWorkflowMock,
  validateWorkflowMock,
} = vi.hoisted(() => ({
  abortMock: vi.fn(),
  createWorkflowStreamRequestMock: vi.fn(),
  getWorkflowMock: vi.fn(),
  validateWorkflowMock: vi.fn(),
}))

vi.mock('react-router-dom', () => ({
  useParams: () => ({ workflowId: 'eebdebb4-e2fd-49bd-bc25-9162a90084be' }),
  useNavigate: () => vi.fn(),
}))

vi.mock('../../api/workflow', () => ({
  getWorkflow: getWorkflowMock,
  validateWorkflow: validateWorkflowMock,
  executeWorkflowStreamUrl: (id: string) => `/api/workflows/${id}/execute/stream`,
}))

vi.mock('../../utils/streamRequest', () => ({
  createWorkflowStreamRequest: createWorkflowStreamRequestMock,
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
  getWorkflowMock.mockResolvedValue({
    data: {
      id: 'eebdebb4-e2fd-49bd-bc25-9162a90084be',
      name: '可执行工作流',
      status: 'published',
      nodes: [],
      edges: [],
    },
  })
  validateWorkflowMock.mockResolvedValue({ data: { valid: true } })
  createWorkflowStreamRequestMock.mockReturnValue({ abort: abortMock })
})

afterEach(cleanup)

describe('WorkflowExecution', () => {
  it('取消按钮中止当前 SSE 请求并恢复可执行状态', async () => {
    render(<WorkflowExecution />)

    const executeButton = await screen.findByRole('button', { name: /执行工作流/ })
    fireEvent.click(executeButton)

    await waitFor(() => expect(createWorkflowStreamRequestMock).toHaveBeenCalled())
    fireEvent.click(screen.getByRole('button', { name: /取消/ }))

    expect(abortMock).toHaveBeenCalledOnce()
    expect(screen.queryByRole('button', { name: /取消/ })).toBeNull()
  })
})
