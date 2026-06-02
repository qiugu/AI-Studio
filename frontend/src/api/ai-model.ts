import apiClient from './client'
import type { ApiResponse, PaginatedData, PageParams } from '@/types/api'
import type {
  AIProvider,
  AIProviderCreateRequest,
  AIProviderUpdateRequest,
  ConnectivityTestRequest,
  ConnectivityTestResult,
  AIModel,
  AIModelCreateRequest,
  AIModelUpdateRequest,
  ModelTestRequest,
  ModelTestResult,
} from '@/types/ai-model'

// ── 供应商 API ──────────────────────────────────────────────────────────────

export async function listProviders(
  params?: PageParams & { status?: boolean }
): Promise<ApiResponse<PaginatedData<AIProvider>>> {
  const response = await apiClient.get('/providers', { params })
  return response as unknown as ApiResponse<PaginatedData<AIProvider>>
}

export async function getProvider(id: number): Promise<ApiResponse<AIProvider>> {
  const response = await apiClient.get(`/providers/${id}`)
  return response as unknown as ApiResponse<AIProvider>
}

export async function createProvider(
  data: AIProviderCreateRequest
): Promise<ApiResponse<AIProvider>> {
  const response = await apiClient.post('/providers', data)
  return response as unknown as ApiResponse<AIProvider>
}

export async function updateProvider(
  id: number,
  data: AIProviderUpdateRequest
): Promise<ApiResponse<AIProvider>> {
  const response = await apiClient.put(`/providers/${id}`, data)
  return response as unknown as ApiResponse<AIProvider>
}

export async function deleteProvider(id: number): Promise<ApiResponse<null>> {
  const response = await apiClient.delete(`/providers/${id}`)
  return response as unknown as ApiResponse<null>
}

export async function testProviderConnectivity(
  id: number,
  data: ConnectivityTestRequest
): Promise<ApiResponse<ConnectivityTestResult>> {
  const response = await apiClient.post(`/providers/${id}/test`, data)
  return response as unknown as ApiResponse<ConnectivityTestResult>
}

// ── 模型 API ──────────────────────────────────────────────────────────────

export async function listModels(
  params?: PageParams & {
    model_type?: string
    provider_id?: number
    include_public?: boolean
  }
): Promise<ApiResponse<PaginatedData<AIModel>>> {
  const response = await apiClient.get('/ai-models', { params })
  return response as unknown as ApiResponse<PaginatedData<AIModel>>
}

export async function getModel(id: number): Promise<ApiResponse<AIModel>> {
  const response = await apiClient.get(`/ai-models/${id}`)
  return response as unknown as ApiResponse<AIModel>
}

export async function createModel(
  data: AIModelCreateRequest
): Promise<ApiResponse<AIModel>> {
  const response = await apiClient.post('/ai-models', data)
  return response as unknown as ApiResponse<AIModel>
}

export async function updateModel(
  id: number,
  data: AIModelUpdateRequest
): Promise<ApiResponse<AIModel>> {
  const response = await apiClient.put(`/ai-models/${id}`, data)
  return response as unknown as ApiResponse<AIModel>
}

export async function deleteModel(id: number): Promise<ApiResponse<null>> {
  const response = await apiClient.delete(`/ai-models/${id}`)
  return response as unknown as ApiResponse<null>
}

export async function testModel(
  id: number,
  data: ModelTestRequest
): Promise<ApiResponse<ModelTestResult>> {
  const response = await apiClient.post(`/ai-models/${id}/test`, data)
  return response as unknown as ApiResponse<ModelTestResult>
}
