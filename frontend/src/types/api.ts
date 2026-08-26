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
  id: string
  tenant_id: string
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
  id: string
  tenant_id?: string
  name: string
  code: string
  description?: string | null
  status: boolean
  permissions: Permission[]
}

export interface Permission {
  id: string
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

// ── 监控审计 ────────────────────────────────────────────────────────────────
export interface AuditLog {
  id: string
  tenant_id: string
  user_id: string | null
  action: string
  resource: string
  resource_id: string | null
  method: string
  path: string
  status_code: number
  ip_address: string | null
  duration_ms: number
  created_at: string | null
}

export interface ModelCallLog {
  id: string
  tenant_id: string
  user_id: string | null
  agent_id: string | null
  model_id: string
  provider_id: string | null
  conversation_id: string | null
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  latency_ms: number
  status: string
  error_message: string | null
  created_at: string | null
}

export interface TokenTrendPoint {
  date: string
  total_tokens: number
  call_count: number
}

export interface TokenGroupItem {
  key: string | null
  total_tokens: number
  call_count: number
}

export interface TokenStats {
  start_time: string
  end_time: string
  totals: TokenGroupItem
  trend: TokenTrendPoint[]
  by_model: TokenGroupItem[]
  by_agent: TokenGroupItem[]
  by_user: TokenGroupItem[]
}

export interface DashboardStats {
  active_users: number
  total_agents: number
  total_tokens_30d: number
  total_calls_30d: number
  token_trend: TokenTrendPoint[]
  top_models: TokenGroupItem[]
}

// ── 用户管理 ────────────────────────────────────────────────────────────────
export interface UserCreateRequest {
  email: string
  password: string
  nickname?: string
  role_ids?: string[]
}

export interface UserUpdateRequest {
  nickname?: string
  password?: string
  status?: boolean
  role_ids?: string[]
}

export interface UserRoleAssign {
  role_ids: string[]
}

// ── 角色权限 ────────────────────────────────────────────────────────────────
export interface RoleCreateRequest {
  name: string
  description?: string
  permission_ids?: string[]
}

export interface RoleUpdateRequest {
  name?: string
  description?: string
  status?: boolean
}

export interface RolePermissionAssign {
  permission_ids: string[]
}

// ── 租户设置 / 平台管理 ───────────────────────────────────────────────────────
export interface TenantUsage {
  user_count: number
  model_count: number
  agent_count: number
  knowledge_base_count: number
}

export interface TenantSettings {
  id: string
  name: string
  description: string | null
  plan: string
  max_users: number
  max_models: number
  status: boolean
  created_at: string | null
  usage: TenantUsage
}

export interface AdminTenant {
  id: string
  name: string
  description: string | null
  plan: string
  max_users: number
  max_models: number
  status: boolean
  is_system_init: boolean
  created_at: string | null
  usage: TenantUsage | null
}

export interface TenantCreateRequest {
  name: string
  description?: string
  plan?: string
  max_users?: number
  max_models?: number
}

export interface TenantUpdateRequest {
  name?: string
  description?: string
  plan?: string
  status?: boolean
}

export interface TenantQuotaUpdate {
  max_users?: number
  max_models?: number
}