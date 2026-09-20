// ── Agent 工具 ───────────────────────────────────────────────────────────────

import type { PluginSourceType } from '@/types/plugin'
import type { ChunkType } from '@/types/knowledge'

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

// ── Agent 可绑定插件目录（候选清单） ─────────────────────────────────────────

/**
 * 目录中的插件端点。端点是「可被授权」的原子单位——选中它，模型才可能调用它。
 */
export interface ToolCatalogEndpoint {
  id: string
  endpoint: string
  method: string
  description: string | null
  /** 破坏性动词（DELETE/PUT/PATCH），选中前需用户显式确认 */
  is_destructive: boolean
}

/**
 * 可绑定为 Agent 工具的插件。服务端已按 归属 / 状态 / 接入方式 / 端点数量 裁剪，
 * 前端只需展示，不应重复判断「是否可用」，否则两端口径会漂移。
 */
export interface ToolCatalogPlugin {
  id: string
  name: string
  source_type: PluginSourceType
  description: string | null
  icon: string | null
  /** 平台公共插件（tenant_id 为空），所有租户可绑定 */
  is_public: boolean
  endpoints: ToolCatalogEndpoint[]
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
  /** 引用溯源（Phase 1）：本轮对话命中知识库块的来源快照；无引用时为 null/空 */
  citations?: Citation[] | null
}

/**
 * 引用溯源对象（与后端 `CitationCollector` 产出的 Citation 一致，见 docs/citation-traceability.md §5.1）。
 * 数据来自「已通过租户过滤的检索结果」快照，不引入跨租户取全文的新端点（R8）。
 */
export interface Citation {
  marker: number // 角标编号，1 基，单轮内唯一且稳定（轮次内编号，非检索响应内编号）
  chunk_id: string // knowledge_chunks.id
  doc_id: string
  doc_name: string
  kb_id?: string | null
  chunk_index?: number | null
  source_page?: number | null // 闭区间起点；非 PDF 为 null
  source_page_end?: number | null // 闭区间终点；与起点相同表示单页
  heading_path?: string | null // md/docx 可得；PDF 为 null
  heading_path_mixed?: boolean | null // true 表示 heading_path 仅为共同祖先，前端显示「等小节」
  /**
   * 块类型。引用面板据此选择渲染方式——表格需按列渲染、代码需保留换行，
   * 两者按纯文本渲染都会丢掉关键结构。
   *
   * 可缺省：**存量引用对象**（`messages.citations` 里已落库的历史消息）没有该键，
   * 消费方须按 `text` 处理，不能假定它一定存在。
   */
  chunk_type?: ChunkType | null
  score?: number | null
  content: string // 命中块原文快照（权威展示源，分块重建后仍可展示，R1）
  llm_content?: string | null // 仅当 context_expanded 为 true 时出现（上下文窗口文本）
  context_header?: string | null // 如「[《手册.pdf》 | §3.2 | p.37–38]」
  context_expanded?: boolean
  tool_name?: string | null // 哪个工具召回
  query?: string | null // 触发召回的查询
  content_truncated?: boolean // top_k > 20 时 content 被截断的标记
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
  citations?: Citation[] // 冗余携带完整引用，作为前端丢包的兜底（D5）
}

export interface SSECitationsEvent {
  citations: Citation[]
  tool?: string
  query?: string
}

export interface SSEErrorEvent {
  error: string
  error_code?: string
}