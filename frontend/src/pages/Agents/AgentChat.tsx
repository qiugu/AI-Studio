/**
 * Agent对话页面 - Professional AI Conversation Interface
 */

import { useState, useEffect, useRef } from 'react'
import { useParams } from 'react-router-dom'
import { Spin, Empty, Drawer, message } from 'antd'
import { HistoryOutlined } from '@ant-design/icons'
import * as agentApi from '@/api/agent'
import { type Agent, type Conversation, type Message } from '@/types/agent'
import { createStreamRequest } from '@/utils/streamRequest'
import {
  AgentInfo,
  ChatContainer,
  ChatInput,
  ConversationList,
} from '@/components/Chat'
import './AgentChat.css'

export default function AgentChat() {
  const { agentId } = useParams<{ agentId: string }>()
  const [agent, setAgent] = useState<Agent | null>(null)
  const [loading, setLoading] = useState(true)
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [currentConversation, setCurrentConversation] = useState<Conversation | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [isStreaming, setIsStreaming] = useState(false)
  const [drawerVisible, setDrawerVisible] = useState(false)
  const abortControllerRef = useRef<AbortController | null>(null)

  useEffect(() => {
    if (agentId) {
      loadAgent()
      loadConversations()
    }
  }, [agentId])

  /**
   * 将错误消息作为助手消息添加到聊天记录中
   */
  const addErrorToChat = (errorContent: string, errorCode?: string) => {
    const errorMessage: Message = {
      id: `${Date.now()}`,
      conversation_id: currentConversation?.id || '',
      tenant_id: agent?.tenant_id || '',
      role: 'assistant',
      content: errorContent,
      prompt_tokens: 0,
      completion_tokens: 0,
      total_tokens: 0,
      tool_calls: null,
      tool_call_id: null,
      tool_name: null,
      created_at: new Date().toISOString(),
      is_error: true,
      error_code: errorCode,
    }
    setMessages((prev) => [...prev, errorMessage])
  }

  const loadAgent = async () => {
    setLoading(true)
    try {
      const { data } = await agentApi.getAgent(agentId || '')
      setAgent(data)
    } catch (error) {
      console.error('Failed to load agent:', error)
      message.error('加载Agent信息失败')
    } finally {
      setLoading(false)
    }
  }

  const loadConversations = async () => {
    try {
      const { data } = await agentApi.listConversations(agentId || '', 1, 20)
      setConversations(data.items)
    } catch (error) {
      console.error('Failed to load conversations:', error)
    }
  }

  const loadConversationMessages = async (conversationId: string) => {
    try {
      const { data } = await agentApi.getConversation(conversationId)
      setCurrentConversation(data)
      setMessages(data.messages || [])
    } catch (error) {
      console.error('Failed to load conversation messages:', error)
      message.error('加载对话历史失败')
    }
  }

  const handleSendMessage = async (content: string) => {
    if (!content.trim() || isStreaming) return

    // 创建用户消息
    const userMessage: Message = {
      id: `${Date.now()}`,
      conversation_id: currentConversation?.id || '',
      tenant_id: agent?.tenant_id || '',
      role: 'user',
      content: content,
      prompt_tokens: 0,
      completion_tokens: 0,
      total_tokens: 0,
      tool_calls: null,
      tool_call_id: null,
      tool_name: null,
      created_at: new Date().toISOString(),
    }

    // 创建助手消息占位符（用于流式更新）
    const assistantMessageId = `${Date.now() + 1}`
    const assistantMessagePlaceholder: Message = {
      id: assistantMessageId,
      conversation_id: currentConversation?.id || '',
      tenant_id: agent?.tenant_id || '',
      role: 'assistant',
      content: '',
      prompt_tokens: 0,
      completion_tokens: 0,
      total_tokens: 0,
      tool_calls: null,
      tool_call_id: null,
      tool_name: null,
      created_at: new Date().toISOString(),
    }

    // 使用函数式更新，在同一个状态更新中获取最新的 messages 状态
    let historyMessages: Array<{ role: string; content: string }> = []
    setMessages((prev) => {
      // 添加用户消息后的新状态
      const newMessages = [...prev, userMessage]

      // 构建历史消息数组（使用更新后的消息列表）
      historyMessages = newMessages
        .slice(-20) // 只保留最近 20 条历史消息
        .filter((msg) => !msg.is_error) // 过滤掉错误消息
        .map((msg) => ({
          role: msg.role,
          content: msg.content,
        }))

      // 调试日志：显示历史消息数量和内容
      console.log('[DEBUG] History messages to send:', {
        prevCount: prev.length,
        historyCount: historyMessages.length,
        currentMessage: content,
        historyPreview: historyMessages.slice(0, 3).map(m => ({ role: m.role, content: m.content.substring(0, 50) }))
      })

      return newMessages
    })

    // 添加助手消息占位符
    setMessages((prev) => [...prev, assistantMessagePlaceholder])
    setIsStreaming(true)

    // 使用 fetch + ReadableStream 发起流式请求
    abortControllerRef.current = createStreamRequest(
      `/api/agent/agents/${agentId || ''}/chat/stream`,
      {
        message: content,
        conversation_id: currentConversation?.id,
        messages: historyMessages,
      },
      {
        onContent: (chunk) => {
          // 更新助手消息内容（流式更新）
          setMessages((prev) =>
            prev.map((msg) =>
              msg.id === assistantMessageId
                ? { ...msg, content: msg.content + chunk }
                : msg
            )
          )
        },
        onComplete: (fullContent, conversationId) => {
          // 流式完成，更新对话 ID 和消息状态
          if (conversationId && !currentConversation) {
            setCurrentConversation({
              id: conversationId,
              tenant_id: agent?.tenant_id || '',
              agent_id: agentId || '',
              title: '新对话',
              created_by: null,
              created_at: new Date().toISOString(),
              updated_at: new Date().toISOString(),
              messages: [],
            })
          }

          // 更新助手消息的最终内容
          setMessages((prev) =>
            prev.map((msg) =>
              msg.id === assistantMessageId
                ? { ...msg, content: fullContent }
                : msg
            )
          )

          setIsStreaming(false)
          abortControllerRef.current = null
          loadConversations()
        },
        onError: (error) => {
          // 将错误消息添加到聊天记录中
          addErrorToChat(error)
          // 移除助手消息占位符
          setMessages((prev) => prev.filter((msg) => msg.id !== assistantMessageId))
          setIsStreaming(false)
          abortControllerRef.current = null
        },
      }
    )
  }

  /**
   * 中断流式请求
   */
  const handleAbortStream = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
      abortControllerRef.current = null
      setIsStreaming(false)
      message.info('已停止生成')
    }
  }

  const handleCreateNewConversation = () => {
    setCurrentConversation(null)
    setMessages([])
    setDrawerVisible(false)
  }

  const handleSelectConversation = (conv: Conversation) => {
    loadConversationMessages(conv.id)
    setDrawerVisible(false)
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full p-6">
        <Spin size="large" />
      </div>
    )
  }

  if (!agent) {
    return (
      <div className="flex items-center justify-center h-full p-6">
        <Empty description="Agent不存在" />
      </div>
    )
  }

  return (
    <div className="agent-chat-container">
      {/* 智能渐变顶栏 */}
      <div className="intelligence-bar" />

      {/* Agent 信息区域 */}
      <div className="agent-info-wrapper">
        <AgentInfo agent={agent} />
      </div>

      {/* 消息列表区域 */}
      <div className="messages-wrapper">
        <ChatContainer messages={messages} isStreaming={isStreaming} />
      </div>

      {/* 输入框区域 */}
      <div className="input-wrapper">
        <ChatInput
          onSend={handleSendMessage}
          onCancel={handleAbortStream}
          isLoading={isStreaming}
          disabled={isStreaming}
        />
      </div>

      {/* 对话历史按钮 */}
      <button
        className="history-toggle-button"
        onClick={() => setDrawerVisible(true)}
      >
        <HistoryOutlined />
        <span>对话历史</span>
      </button>

      {/* 对话历史抽屉 */}
      <Drawer
        title="对话历史"
        placement="right"
        size={400}
        open={drawerVisible}
        onClose={() => setDrawerVisible(false)}
      >
        <ConversationList
          conversations={conversations}
          currentConversationId={currentConversation?.id}
          onSelect={handleSelectConversation}
          onCreateNew={handleCreateNewConversation}
        />
      </Drawer>
    </div>
  )
}