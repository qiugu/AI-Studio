import apiClient from './client'
import type { ApiResponse, TenantCreateRequest, TenantCreateResponse } from '@/types/api'

export async function createTenant(
  data: TenantCreateRequest,
): Promise<ApiResponse<TenantCreateResponse>> {
  const response = await apiClient.post('/admin/tenants', data)
  return response as unknown as ApiResponse<TenantCreateResponse>
}
