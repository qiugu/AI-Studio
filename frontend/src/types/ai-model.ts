// ── AI 供应商 ──────────────────────────────────────────────────────────────

export type ProviderType =
  | 'openai'
  | 'anthropic'
  | 'azure'
  | 'zhipu'
  | 'baichuan'
  | 'ollama'
  | 'custom'

export interface AIProvider {
  id: number
  tenant_id: number
  name: string
  provider_type: ProviderType
  api_base_url: string | null
  has_api_key: boolean
  config: Record<string, unknown> | null
  status: boolean
  created_at: string | null
  updated_at: string | null
}

export interface AIProviderCreateRequest {
  name: string
  provider_type: ProviderType
  api_base_url?: string
  api_key?: string
  config?: Record<string, unknown>
  status?: boolean
}

export interface AIProviderUpdateRequest {
  name?: string
  provider_type?: ProviderType
  api_base_url?: string
  api_key?: string
  config?: Record<string, unknown>
  status?: boolean
}

export interface ConnectivityTestRequest {
  model_name: string
}

export interface ConnectivityTestResult {
  success: boolean
  latency_ms: number | null
  error: string | null
}

// ── AI 模型 ───────────────────────────────────────────────────────────────

export type ModelType = 'chat' | 'embedding' | 'image' | 'audio' | 'rerank'

export interface AIModel {
  id: number
  tenant_id: number | null
  provider_id: number
  name: string
  display_name: string
  model_type: ModelType
  config: Record<string, unknown> | null
  unit_price_input: string | null
  unit_price_output: string | null
  max_context_tokens: number | null
  max_output_tokens: number | null
  status: boolean
  created_at: string | null
  updated_at: string | null
}

export interface AIModelCreateRequest {
  provider_id: number
  name: string
  display_name: string
  model_type: ModelType
  config?: Record<string, unknown>
  unit_price_input?: string
  unit_price_output?: string
  max_context_tokens?: number
  max_output_tokens?: number
  status?: boolean
}

export interface AIModelUpdateRequest {
  name?: string
  display_name?: string
  model_type?: ModelType
  config?: Record<string, unknown>
  unit_price_input?: string
  unit_price_output?: string
  max_context_tokens?: number
  max_output_tokens?: number
  status?: boolean
}

export interface ModelTestRequest {
  messages: Array<{ role: 'user' | 'assistant' | 'system'; content: string }>
}

export interface ModelTestResult {
  content: string
  prompt_tokens: number
  completion_tokens: number
  latency_ms: number
}
