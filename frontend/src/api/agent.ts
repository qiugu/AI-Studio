/**
 * Agent API 客户端
 */

import client from './client'
import type { ApiResponse, PaginatedData } from '@/types/api'
import type {
  Agent,
  AgentCreateRequest,
  AgentUpdateRequest,
  Conversation,
  ConversationCreateRequest,
  ConversationUpdateRequest,
  ChatRequest,
  ChatResponse,
  ToolCatalogPlugin,
} from '@/types/agent'

/**
 * Agent 管理 API
 */

// 创建 Agent
export async function createAgent(data: AgentCreateRequest): Promise<ApiResponse<Agent>> {
  return client.post('/agent/agents', data) as Promise<ApiResponse<Agent>>
}

// 列出 Agents
export async function listAgents(page = 1, pageSize = 20, status?: string): Promise<ApiResponse<PaginatedData<Agent>>> {
  let url = `/agent/agents?page=${page}&page_size=${pageSize}`
  if (status) url += `&status=${status}`
  return client.get(url) as Promise<ApiResponse<PaginatedData<Agent>>>
}

// 获取 Agent 详情
export async function getAgent(agentId: string): Promise<ApiResponse<Agent>> {
  return client.get(`/agent/agents/${agentId}`) as Promise<ApiResponse<Agent>>
}

// 更新 Agent
export async function updateAgent(agentId: string, data: AgentUpdateRequest): Promise<ApiResponse<Agent>> {
  return client.put(`/agent/agents/${agentId}`, data) as Promise<ApiResponse<Agent>>
}

// 删除 Agent
export async function deleteAgent(agentId: string): Promise<ApiResponse<void>> {
  return client.delete(`/agent/agents/${agentId}`) as Promise<ApiResponse<void>>
}

/**
 * 获取可授权给 Agent 的插件候选目录。
 *
 * 这是设计期的候选面：服务端已按 归属 / 状态 / 接入方式 / 端点数量 裁剪，
 * 前端直接展示即可，不要重复判断「是否可用」，否则两端口径会漂移。
 */
export async function getToolCatalog(params?: {
  plugin_type?: string
  keyword?: string
}): Promise<ApiResponse<ToolCatalogPlugin[]>> {
  const search = new URLSearchParams()
  if (params?.plugin_type) search.set('plugin_type', params.plugin_type)
  if (params?.keyword) search.set('keyword', params.keyword)
  const query = search.toString()
  return client.get(
    `/agent/agents/tool-catalog${query ? `?${query}` : ''}`
  ) as Promise<ApiResponse<ToolCatalogPlugin[]>>
}

/**
 * 对话管理 API
 */

// 创建对话
export async function createConversation(data: ConversationCreateRequest): Promise<ApiResponse<Conversation>> {
  return client.post('/agent/conversations', data) as Promise<ApiResponse<Conversation>>
}

// 列出对话
export async function listConversations(agentId: string, page = 1, pageSize = 20): Promise<ApiResponse<PaginatedData<Conversation>>> {
  return client.get(`/agent/agents/${agentId}/conversations?page=${page}&page_size=${pageSize}`) as Promise<ApiResponse<PaginatedData<Conversation>>>
}

// 获取对话详情
export async function getConversation(conversationId: string): Promise<ApiResponse<Conversation>> {
  return client.get(`/agent/conversations/${conversationId}`) as Promise<ApiResponse<Conversation>>
}

// 更新对话
export async function updateConversation(conversationId: string, data: ConversationUpdateRequest): Promise<ApiResponse<Conversation>> {
  return client.put(`/agent/conversations/${conversationId}`, data) as Promise<ApiResponse<Conversation>>
}

// 删除对话
export async function deleteConversation(conversationId: string): Promise<ApiResponse<void>> {
  return client.delete(`/agent/conversations/${conversationId}`) as Promise<ApiResponse<void>>
}

/**
 * 聊天 API
 */

// Agent对话（阻塞式）
export async function chat(
  agentId: string,
  data: ChatRequest,
  config?: { _suppressErrorMessage?: boolean }
): Promise<ApiResponse<ChatResponse>> {
  return client.post(`/agent/agents/${agentId}/chat`, data, config as any) as Promise<ApiResponse<ChatResponse>>
}

// Agent对话（SSE流式）- 返回 EventSource URL
export function getChatStreamUrl(agentId: string): string {
  return `/api/agent/agents/${agentId}/chat/stream`
}