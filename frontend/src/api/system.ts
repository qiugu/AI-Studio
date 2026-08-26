import apiClient from './client'
import type { ApiResponse } from '@/types/api'
import type { TenantSettings } from '@/types/api'

export async function getTenantSettings(): Promise<ApiResponse<TenantSettings>> {
  const response = await apiClient.get('/system/tenant')
  return response as unknown as ApiResponse<TenantSettings>
}

export async function updateTenantSettings(data: {
  name?: string
  description?: string
}): Promise<ApiResponse<TenantSettings>> {
  const response = await apiClient.put('/system/tenant', data)
  return response as unknown as ApiResponse<TenantSettings>
}
