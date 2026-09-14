import apiClient, { AI_REQUEST_TIMEOUT } from './client'
import type { ApiResponse, PaginatedData, PageParams } from '@/types/api'
import type {
  Workflow,
  WorkflowCreateRequest,
  WorkflowUpdateRequest,
  WorkflowExecution,
  WorkflowExecutionRequest,
} from '@/types/workflow'

// ── Workflow CRUD ───────────────────────────────────────────────────────────────

export async function createWorkflow(data: WorkflowCreateRequest): Promise<ApiResponse<Workflow>> {
  const response = await apiClient.post('/workflows', data)
  return response as unknown as ApiResponse<Workflow>
}

export async function getWorkflow(workflowId: string): Promise<ApiResponse<Workflow>> {
  const response = await apiClient.get(`/workflows/${workflowId}`)
  return response as unknown as ApiResponse<Workflow>
}

export async function listWorkflows(
  params?: PageParams & { status?: string }
): Promise<ApiResponse<PaginatedData<Workflow>>> {
  const response = await apiClient.get('/workflows', { params })
  return response as unknown as ApiResponse<PaginatedData<Workflow>>
}

export async function updateWorkflow(
  workflowId: string,
  data: WorkflowUpdateRequest
): Promise<ApiResponse<Workflow>> {
  const response = await apiClient.put(`/workflows/${workflowId}`, data)
  return response as unknown as ApiResponse<Workflow>
}

export async function deleteWorkflow(workflowId: string): Promise<ApiResponse<null>> {
  const response = await apiClient.delete(`/workflows/${workflowId}`)
  return response as unknown as ApiResponse<null>
}

// ── Workflow状态管理 ───────────────────────────────────────────────────────────

export async function publishWorkflow(workflowId: string): Promise<ApiResponse<Workflow>> {
  const response = await apiClient.post(`/workflows/${workflowId}/publish`)
  return response as unknown as ApiResponse<Workflow>
}

export async function archiveWorkflow(workflowId: string): Promise<ApiResponse<Workflow>> {
  const response = await apiClient.post(`/workflows/${workflowId}/archive`)
  return response as unknown as ApiResponse<Workflow>
}

// ── Workflow验证 ───────────────────────────────────────────────────────────────

export interface WorkflowValidateResult {
  valid: boolean
  node_count: number
  edge_count: number
}

export async function validateWorkflow(
  workflowId: string
): Promise<ApiResponse<WorkflowValidateResult>> {
  const response = await apiClient.get(`/workflows/${workflowId}/validate`)
  return response as unknown as ApiResponse<WorkflowValidateResult>
}

// ── Workflow执行 ───────────────────────────────────────────────────────────────

export async function executeWorkflow(
  workflowId: string,
  data: WorkflowExecutionRequest
): Promise<ApiResponse<WorkflowExecution>> {
  // 工作流执行含多次模型调用，使用 AI 专用超时
  const response = await apiClient.post(`/workflows/${workflowId}/execute`, data, {
    timeout: AI_REQUEST_TIMEOUT,
  })
  return response as unknown as ApiResponse<WorkflowExecution>
}

export function executeWorkflowStreamUrl(workflowId: string): string {
  return `/api/workflows/${workflowId}/execute/stream`
}