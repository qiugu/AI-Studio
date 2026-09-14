// ── 插件系统 ────────────────────────────────────────────────────────────────

// 维度 A · 能力形态（插件「做什么」）
export type PluginType = 'tool' | 'connector' | 'processor'

// 维度 B · 接入方式（插件「怎么接进来」）
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
  plugin_type: PluginType
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
  plugin_type?: PluginType
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
  plugin_type?: PluginType
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
