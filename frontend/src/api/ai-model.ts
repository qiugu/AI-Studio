import apiClient, { AI_REQUEST_TIMEOUT } from './client'
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

export async function getProvider(id: string): Promise<ApiResponse<AIProvider>> {
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
  id: string,
  data: AIProviderUpdateRequest
): Promise<ApiResponse<AIProvider>> {
  const response = await apiClient.put(`/providers/${id}`, data)
  return response as unknown as ApiResponse<AIProvider>
}

export async function deleteProvider(id: string): Promise<ApiResponse<null>> {
  const response = await apiClient.delete(`/providers/${id}`)
  return response as unknown as ApiResponse<null>
}

export async function testProviderConnectivity(
  id: string,
  data: ConnectivityTestRequest
): Promise<ApiResponse<ConnectivityTestResult>> {
  // 连通性检测会真实调用供应商接口，使用 AI 专用超时
  const response = await apiClient.post(`/providers/${id}/test`, data, {
    timeout: AI_REQUEST_TIMEOUT,
  })
  return response as unknown as ApiResponse<ConnectivityTestResult>
}

// ── 模型 API ──────────────────────────────────────────────────────────────

export async function listModels(
  params?: PageParams & {
    model_type?: string
    provider_id?: string
    include_public?: boolean
  }
): Promise<ApiResponse<PaginatedData<AIModel>>> {
  const response = await apiClient.get('/ai-models', { params })
  return response as unknown as ApiResponse<PaginatedData<AIModel>>
}

export async function getModel(id: string): Promise<ApiResponse<AIModel>> {
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
  id: string,
  data: AIModelUpdateRequest
): Promise<ApiResponse<AIModel>> {
  const response = await apiClient.put(`/ai-models/${id}`, data)
  return response as unknown as ApiResponse<AIModel>
}

export async function deleteModel(id: string): Promise<ApiResponse<null>> {
  const response = await apiClient.delete(`/ai-models/${id}`)
  return response as unknown as ApiResponse<null>
}

export async function testModel(
  id: string,
  data: ModelTestRequest
): Promise<ApiResponse<ModelTestResult>> {
  // 模型测试会真实推理，使用 AI 专用超时
  const response = await apiClient.post(`/ai-models/${id}/test`, data, {
    timeout: AI_REQUEST_TIMEOUT,
  })
  return response as unknown as ApiResponse<ModelTestResult>
}
