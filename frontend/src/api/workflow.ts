import apiClient from './client'
import type { ApiResponse, PaginatedData, PageParams } from '@/types/api'
import type {
  Workflow,
  WorkflowCreateRequest,
  WorkflowUpdateRequest,
  WorkflowListResponse,
  WorkflowExecution,
  WorkflowExecutionRequest,
} from '@/types/workflow'

// ── Workflow CRUD ───────────────────────────────────────────────────────────────

export async function createWorkflow(data: WorkflowCreateRequest): Promise<ApiResponse<Workflow>> {
  const response = await apiClient.post('/workflows', data)
  return response as unknown as ApiResponse<Workflow>
}

export async function getWorkflow(workflowId: number): Promise<ApiResponse<Workflow>> {
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
  workflowId: number,
  data: WorkflowUpdateRequest
): Promise<ApiResponse<Workflow>> {
  const response = await apiClient.put(`/workflows/${workflowId}`, data)
  return response as unknown as ApiResponse<Workflow>
}

export async function deleteWorkflow(workflowId: number): Promise<ApiResponse<null>> {
  const response = await apiClient.delete(`/workflows/${workflowId}`)
  return response as unknown as ApiResponse<null>
}

// ── Workflow状态管理 ───────────────────────────────────────────────────────────

export async function publishWorkflow(workflowId: number): Promise<ApiResponse<Workflow>> {
  const response = await apiClient.post(`/workflows/${workflowId}/publish`)
  return response as unknown as ApiResponse<Workflow>
}

export async function archiveWorkflow(workflowId: number): Promise<ApiResponse<Workflow>> {
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
  workflowId: number
): Promise<ApiResponse<WorkflowValidateResult>> {
  const response = await apiClient.get(`/workflows/${workflowId}/validate`)
  return response as unknown as ApiResponse<WorkflowValidateResult>
}

// ── Workflow执行 ───────────────────────────────────────────────────────────────

export async function executeWorkflow(
  workflowId: number,
  data: WorkflowExecutionRequest
): Promise<ApiResponse<WorkflowExecution>> {
  const response = await apiClient.post(`/workflows/${workflowId}/execute`, data)
  return response as unknown as ApiResponse<WorkflowExecution>
}

export function executeWorkflowStreamUrl(workflowId: number): string {
  return `/api/workflows/${workflowId}/execute/stream`
}