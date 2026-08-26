import apiClient from './client'
import type { ApiResponse, PaginatedData, PageParams } from '@/types/api'
import type {
  Role,
  Permission,
  RoleCreateRequest,
  RoleUpdateRequest,
  RolePermissionAssign,
} from '@/types/api'

export async function listRoles(
  params?: PageParams
): Promise<ApiResponse<PaginatedData<Role>>> {
  const response = await apiClient.get('/roles', { params })
  return response as unknown as ApiResponse<PaginatedData<Role>>
}

export async function createRole(
  data: RoleCreateRequest
): Promise<ApiResponse<Role>> {
  const response = await apiClient.post('/roles', data)
  return response as unknown as ApiResponse<Role>
}

export async function getRole(id: string): Promise<ApiResponse<Role>> {
  const response = await apiClient.get(`/roles/${id}`)
  return response as unknown as ApiResponse<Role>
}

export async function updateRole(
  id: string,
  data: RoleUpdateRequest
): Promise<ApiResponse<Role>> {
  const response = await apiClient.put(`/roles/${id}`, data)
  return response as unknown as ApiResponse<Role>
}

export async function deleteRole(id: string): Promise<ApiResponse<null>> {
  const response = await apiClient.delete(`/roles/${id}`)
  return response as unknown as ApiResponse<null>
}

export async function listPermissions(): Promise<ApiResponse<Permission[]>> {
  const response = await apiClient.get('/roles/permissions/all')
  return response as unknown as ApiResponse<Permission[]>
}

export async function setRolePermissions(
  id: string,
  data: RolePermissionAssign
): Promise<ApiResponse<Role>> {
  const response = await apiClient.put(`/roles/${id}/permissions`, data)
  return response as unknown as ApiResponse<Role>
}
