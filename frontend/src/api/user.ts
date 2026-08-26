import apiClient from './client'
import type { ApiResponse, PaginatedData, PageParams } from '@/types/api'
import type {
  User,
  UserCreateRequest,
  UserUpdateRequest,
  UserRoleAssign,
} from '@/types/api'

export async function listUsers(
  params?: PageParams & { search?: string; status?: boolean }
): Promise<ApiResponse<PaginatedData<User>>> {
  const response = await apiClient.get('/users', { params })
  return response as unknown as ApiResponse<PaginatedData<User>>
}

export async function createUser(
  data: UserCreateRequest
): Promise<ApiResponse<User>> {
  const response = await apiClient.post('/users', data)
  return response as unknown as ApiResponse<User>
}

export async function getUser(id: string): Promise<ApiResponse<User>> {
  const response = await apiClient.get(`/users/${id}`)
  return response as unknown as ApiResponse<User>
}

export async function updateUser(
  id: string,
  data: UserUpdateRequest
): Promise<ApiResponse<User>> {
  const response = await apiClient.put(`/users/${id}`, data)
  return response as unknown as ApiResponse<User>
}

export async function deleteUser(id: string): Promise<ApiResponse<null>> {
  const response = await apiClient.delete(`/users/${id}`)
  return response as unknown as ApiResponse<null>
}

export async function assignUserRoles(
  id: string,
  data: UserRoleAssign
): Promise<ApiResponse<User>> {
  const response = await apiClient.post(`/users/${id}/roles`, data)
  return response as unknown as ApiResponse<User>
}
