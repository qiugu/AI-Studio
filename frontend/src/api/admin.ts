import apiClient from './client'
import type { ApiResponse, PaginatedData, PageParams } from '@/types/api'
import type {
  AdminTenant,
  TenantCreateRequest,
  TenantUpdateRequest,
  TenantQuotaUpdate,
} from '@/types/api'
import type {
  AIModel,
  AIModelCreateRequest,
  AIModelUpdateRequest,
} from '@/types/ai-model'

// ── 租户管理 ────────────────────────────────────────────────────────────────
export async function listTenants(
  params?: PageParams & { search?: string }
): Promise<ApiResponse<PaginatedData<AdminTenant>>> {
  const response = await apiClient.get('/admin/tenants', { params })
  return response as unknown as ApiResponse<PaginatedData<AdminTenant>>
}

export async function getTenant(id: string): Promise<ApiResponse<AdminTenant>> {
  const response = await apiClient.get(`/admin/tenants/${id}`)
  return response as unknown as ApiResponse<AdminTenant>
}

export async function createTenant(
  data: TenantCreateRequest
): Promise<ApiResponse<AdminTenant>> {
  const response = await apiClient.post('/admin/tenants', data)
  return response as unknown as ApiResponse<AdminTenant>
}

export async function updateTenant(
  id: string,
  data: TenantUpdateRequest
): Promise<ApiResponse<AdminTenant>> {
  const response = await apiClient.put(`/admin/tenants/${id}`, data)
  return response as unknown as ApiResponse<AdminTenant>
}

export async function setTenantQuota(
  id: string,
  data: TenantQuotaUpdate
): Promise<ApiResponse<AdminTenant>> {
  const response = await apiClient.put(`/admin/tenants/${id}/quota`, data)
  return response as unknown as ApiResponse<AdminTenant>
}

export async function deleteTenant(id: string): Promise<ApiResponse<null>> {
  const response = await apiClient.delete(`/admin/tenants/${id}`)
  return response as unknown as ApiResponse<null>
}

// ── 平台公共模型 ──────────────────────────────────────────────────────────────
export async function listPublicModels(
  params?: PageParams
): Promise<ApiResponse<PaginatedData<AIModel>>> {
  const response = await apiClient.get('/admin/models', { params })
  return response as unknown as ApiResponse<PaginatedData<AIModel>>
}

export async function createPublicModel(
  data: AIModelCreateRequest
): Promise<ApiResponse<AIModel>> {
  const response = await apiClient.post('/admin/models', data)
  return response as unknown as ApiResponse<AIModel>
}

export async function updatePublicModel(
  id: string,
  data: AIModelUpdateRequest
): Promise<ApiResponse<AIModel>> {
  const response = await apiClient.put(`/admin/models/${id}`, data)
  return response as unknown as ApiResponse<AIModel>
}

export async function deletePublicModel(id: string): Promise<ApiResponse<null>> {
  const response = await apiClient.delete(`/admin/models/${id}`)
  return response as unknown as ApiResponse<null>
}
