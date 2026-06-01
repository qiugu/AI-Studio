import apiClient from './client'
import type {
  ApiResponse,
  LoginRequest,
  LoginResponse,
  RegisterRequest,
  RefreshRequest,
  RefreshResponse,
  User,
} from '@/types/api'

export async function login(data: LoginRequest): Promise<ApiResponse<LoginResponse>> {
  const response = await apiClient.post('/auth/login', data)
  return response as unknown as ApiResponse<LoginResponse>
}

export async function register(data: RegisterRequest): Promise<ApiResponse<User>> {
  const response = await apiClient.post('/auth/register', data)
  return response as unknown as ApiResponse<User>
}

export async function refreshToken(data: RefreshRequest): Promise<ApiResponse<RefreshResponse>> {
  const response = await apiClient.post('/auth/refresh', data)
  return response as unknown as ApiResponse<RefreshResponse>
}

export async function logout(): Promise<ApiResponse<null>> {
  const response = await apiClient.post('/auth/logout')
  return response as unknown as ApiResponse<null>
}

export async function getCurrentUser(): Promise<ApiResponse<User>> {
  const response = await apiClient.get('/auth/me')
  return response as unknown as ApiResponse<User>
}