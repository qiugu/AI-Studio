import apiClient from './client'
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

export async function getPrompt(id: number): Promise<ApiResponse<Prompt>> {
  const response = await apiClient.get(`/prompts/${id}`)
  return response as unknown as ApiResponse<Prompt>
}

export async function createPrompt(data: PromptCreateRequest): Promise<ApiResponse<Prompt>> {
  const response = await apiClient.post('/prompts', data)
  return response as unknown as ApiResponse<Prompt>
}

export async function updatePrompt(
  id: number,
  data: PromptUpdateRequest
): Promise<ApiResponse<Prompt>> {
  const response = await apiClient.put(`/prompts/${id}`, data)
  return response as unknown as ApiResponse<Prompt>
}

export async function deletePrompt(id: number): Promise<ApiResponse<null>> {
  const response = await apiClient.delete(`/prompts/${id}`)
  return response as unknown as ApiResponse<null>
}

export async function listVersions(promptId: number): Promise<ApiResponse<PromptVersion[]>> {
  const response = await apiClient.get(`/prompts/${promptId}/versions`)
  return response as unknown as ApiResponse<PromptVersion[]>
}

export async function createVersion(
  promptId: number,
  data: PromptVersionCreateRequest
): Promise<ApiResponse<PromptVersion>> {
  const response = await apiClient.post(`/prompts/${promptId}/versions`, data)
  return response as unknown as ApiResponse<PromptVersion>
}

export async function activateVersion(
  promptId: number,
  versionId: number
): Promise<ApiResponse<PromptVersion>> {
  const response = await apiClient.put(`/prompts/${promptId}/versions/${versionId}/activate`, {})
  return response as unknown as ApiResponse<PromptVersion>
}

export async function testPrompt(
  promptId: number,
  data: PromptTestRequest
): Promise<ApiResponse<PromptTestResult>> {
  const response = await apiClient.post(`/prompts/${promptId}/test`, data)
  return response as unknown as ApiResponse<PromptTestResult>
}
