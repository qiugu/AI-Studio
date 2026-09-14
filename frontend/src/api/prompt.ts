import apiClient, { AI_REQUEST_TIMEOUT } from './client'
import type { ApiResponse, PaginatedData, PageParams } from '@/types/api'
import type {
  Prompt,
  PromptVersion,
  PromptCreateRequest,
  PromptUpdateRequest,
  PromptVersionCreateRequest,
  PromptTestRequest,
  PromptTestResult,
} from '@/types/prompt'

export async function listPrompts(
  params?: PageParams & { category?: string; status?: string }
): Promise<ApiResponse<PaginatedData<Prompt>>> {
  const response = await apiClient.get('/prompts', { params })
  return response as unknown as ApiResponse<PaginatedData<Prompt>>
}

export async function getPrompt(id: string): Promise<ApiResponse<Prompt>> {
  const response = await apiClient.get(`/prompts/${id}`)
  return response as unknown as ApiResponse<Prompt>
}

export async function createPrompt(data: PromptCreateRequest): Promise<ApiResponse<Prompt>> {
  const response = await apiClient.post('/prompts', data)
  return response as unknown as ApiResponse<Prompt>
}

export async function updatePrompt(
  id: string,
  data: PromptUpdateRequest
): Promise<ApiResponse<Prompt>> {
  const response = await apiClient.put(`/prompts/${id}`, data)
  return response as unknown as ApiResponse<Prompt>
}

export async function deletePrompt(id: string): Promise<ApiResponse<null>> {
  const response = await apiClient.delete(`/prompts/${id}`)
  return response as unknown as ApiResponse<null>
}

export async function listVersions(promptId: string): Promise<ApiResponse<PromptVersion[]>> {
  const response = await apiClient.get(`/prompts/${promptId}/versions`)
  return response as unknown as ApiResponse<PromptVersion[]>
}

export async function createVersion(
  promptId: string,
  data: PromptVersionCreateRequest
): Promise<ApiResponse<PromptVersion>> {
  const response = await apiClient.post(`/prompts/${promptId}/versions`, data)
  return response as unknown as ApiResponse<PromptVersion>
}

export async function activateVersion(
  promptId: string,
  versionId: string
): Promise<ApiResponse<PromptVersion>> {
  const response = await apiClient.put(`/prompts/${promptId}/versions/${versionId}/activate`, {})
  return response as unknown as ApiResponse<PromptVersion>
}

export async function testPrompt(
  promptId: string,
  data: PromptTestRequest
): Promise<ApiResponse<PromptTestResult>> {
  // 模型推理耗时不定，使用 AI 专用超时，避免被默认 30s 提前中断
  const response = await apiClient.post(`/prompts/${promptId}/test`, data, {
    timeout: AI_REQUEST_TIMEOUT,
  })
  return response as unknown as ApiResponse<PromptTestResult>
}
