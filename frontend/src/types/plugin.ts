// ── 插件系统 ────────────────────────────────────────────────────────────────

// 接入方式（插件「怎么接进来」）——插件形态的**唯一**维度。
// 「能力形态」plugin_type 已随 M2.0 移除（边界不可判定、零行为差异）。
export type PluginSourceType = 'http' | 'mcp' | 'skill'

export type PluginStatus = 'active' | 'disabled' | 'pending_review'

export interface PluginEndpoint {
  id: string
  plugin_id: string
  endpoint: string
  method: string
  headers?: Record<string, unknown> | null
  request_body_schema?: Record<string, unknown> | null
  response_schema?: Record<string, unknown> | null
  description?: string | null
  created_at?: string | null
}

export interface Plugin {
  id: string
  tenant_id: string | null
  name: string
  source_type: PluginSourceType
  version: string
  description?: string | null
  config_schema?: Record<string, unknown> | null
  icon?: string | null
  author?: string | null
  homepage_url?: string | null
  api_spec?: Record<string, unknown> | null
  status: PluginStatus
  is_public: boolean
  created_at?: string | null
  updated_at?: string | null
  endpoints: PluginEndpoint[]
}

export interface PluginCreateRequest {
  name: string
  source_type?: PluginSourceType
  version?: string
  description?: string
  config_schema?: Record<string, unknown>
  icon?: string
  author?: string
  homepage_url?: string
  api_spec?: Record<string, unknown>
  is_public?: boolean
  status?: PluginStatus
}

export interface PluginUpdateRequest {
  name?: string
  source_type?: PluginSourceType
  version?: string
  description?: string
  config_schema?: Record<string, unknown>
  icon?: string
  author?: string
  homepage_url?: string
  api_spec?: Record<string, unknown>
  is_public?: boolean
  status?: PluginStatus
}

export interface PluginConfigItem {
  name: string
  value: unknown
  // 是否已设置真实值。敏感项（api_key/secret 等）回显时 value 为 null、has_value 为 true，
  // 前端据此在保存时跳过「空值且原本已设置」的字段，避免把脱敏/缺省值当成新值覆盖。
  has_value?: boolean
}

export interface PluginEndpointCreateRequest {
  endpoint: string
  method?: string
  headers?: Record<string, unknown> | null
  request_body_schema?: Record<string, unknown> | null
  response_schema?: Record<string, unknown> | null
  description?: string | null
}

export interface PluginEndpointUpdateRequest {
  endpoint?: string
  method?: string
  headers?: Record<string, unknown> | null
  request_body_schema?: Record<string, unknown> | null
  response_schema?: Record<string, unknown> | null
  description?: string | null
}

export interface PluginConfigResponse {
  items: PluginConfigItem[]
}

export interface PluginTestRequest {
  endpoint?: string
  method?: string
  params?: Record<string, unknown>
}

export interface PluginTestResult {
  success: boolean
  status_code?: number | null
  latency_ms?: number | null
  data?: unknown
  error?: string | null
}
