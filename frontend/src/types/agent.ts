// ── Agent 工具 ───────────────────────────────────────────────────────────────

export type ToolType = 'knowledge' | 'api' | 'function' | 'workflow' | 'plugin'

export interface AgentTool {
  id: string
  agent_id: string
  tenant_id: string
  tool_type: ToolType
  config: Record<string, unknown>
  name: string
  description: string | null
  is_enabled: boolean
  created_at: string
  updated_at: string
}

export interface AgentToolCreate {
  tool_type: ToolType
  config: Record<string, unknown>
  name: string
  description?: string
  is_enabled?: boolean
}

export interface AgentToolUpdate {
  tool_type?: ToolType
  config?: Record<string, unknown>
  name?: string
  description?: string
  is_enabled?: boolean
}

// ── Agent ────────────────────────────────────────────────────────────────────

export type AgentStatus = 'draft' | 'published' | 'archived'

export interface Agent {
  id: string
  tenant_id: string
  name: string
  description: string | null
  avatar: string | null
  system_prompt: string | null
  model_id: number
  temperature: number
  max_tokens: number
  status: AgentStatus
  created_by: number | null
  created_at: string
  updated_at: string
  deleted_at: string | null
  tools: AgentTool[]
}

export interface AgentCreateRequest {
  name: string
  description?: string
  avatar?: string
  system_prompt?: string
  model_id: number
  temperature?: number
  max_tokens?: number
  status?: AgentStatus
  tools?: AgentToolCreate[]
}

export interface AgentUpdateRequest {
  name?: string
  description?: string
  avatar?: string
  system_prompt?: string
  model_id?: number
  temperature?: number
  max_tokens?: number
  status?: AgentStatus
  tools?: AgentToolCreate[]
}

// ── 消息 ─────────────────────────────────────────────────────────────────────

export type MessageRole = 'user' | 'assistant' | 'system' | 'tool'

export interface Message {
  id: string
  conversation_id: string
  tenant_id: string
  role: MessageRole
  content: string
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  tool_calls: Array<Record<string, unknown>> | null
  tool_call_id: string | null
  tool_name: string | null
  created_at: string
  is_error?: boolean  // 是否为错误消息
  error_code?: string  // 错误代码
}

// ── 对话 ─────────────────────────────────────────────────────────────────────

export interface Conversation {
  id: string
  tenant_id: string
  agent_id: string
  title: string
  created_by: number | null
  created_at: string
  updated_at: string
  messages: Message[]
}

export interface ConversationCreateRequest {
  agent_id: string
  title?: string
}

export interface ConversationUpdateRequest {
  title?: string
}

// ── 聊天 ─────────────────────────────────────────────────────────────────────

export interface ChatRequest {
  message: string
  conversation_id?: string
  stream?: boolean
  messages?: Array<{ role: string; content: string }> // 对话历史消息数组（可选）
}

export interface ChatResponse {
  conversation_id: string
  message: Message
}

export interface SSEMessageEvent {
  content: string
}

export interface SSEDoneEvent {
  content: string
  conversation_id: string
  prompt_tokens?: number
  completion_tokens?: number
  total_tokens?: number
}

export interface SSEErrorEvent {
  error: string
  error_code?: string
}