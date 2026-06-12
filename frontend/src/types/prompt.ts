export type PromptStatus = 'draft' | 'published' | 'archived'

export interface PromptVersion {
  id: number
  prompt_id: number
  version_number: number
  content: string
  variables: string[] | null
  is_current: boolean
  created_by: number | null
  created_at: string | null
}

export interface Prompt {
  id: number
  tenant_id: number
  name: string
  description: string | null
  category: string | null
  tags: string[] | null
  status: PromptStatus
  created_by: number | null
  created_at: string | null
  updated_at: string | null
  current_version: PromptVersion | null
}

export interface PromptCreateRequest {
  name: string
  description?: string
  category?: string
  tags?: string[]
  content: string
}

export interface PromptUpdateRequest {
  name?: string
  description?: string
  category?: string
  tags?: string[]
  status?: PromptStatus
}

export interface PromptVersionCreateRequest {
  content: string
}

export interface PromptTestRequest {
  version_id?: number
  variables: Record<string, string>
  model_id: number
}

export interface PromptTestResult {
  rendered_content: string
  result_content: string
  prompt_tokens: number
  completion_tokens: number
  latency_ms: number
}
