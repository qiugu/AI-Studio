export interface ApiResponse<T = unknown> {
  code: number
  message: string
  data: T
}

export interface PaginatedData<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export type PaginatedResponse<T> = ApiResponse<PaginatedData<T>>

export interface PageParams {
  page?: number
  page_size?: number
}

export interface User {
  id: number
  tenant_id: number
  email: string
  nickname: string | null
  avatar: string | null
  status: boolean
  is_platform_admin: boolean
  last_login_at: string | null
  created_at: string | null
  updated_at: string | null
  roles: Role[]
}

export interface Role {
  id: number
  tenant_id?: number
  name: string
  code: string
  description?: string | null
  status: boolean
  permissions: Permission[]
}

export interface Permission {
  id: number
  resource: string
  action: string
  description?: string | null
}

export interface LoginRequest {
  email: string
  password: string
}

export interface LoginResponse {
  access_token: string
  refresh_token: string
  user: User
}

export interface RegisterRequest {
  email: string
  nickname?: string
  password: string
  password_repeat: string
}

export interface RefreshRequest {
  refresh_token: string
}

export interface RefreshResponse {
  access_token: string
}