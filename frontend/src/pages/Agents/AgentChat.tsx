/**
 * Agent对话页面 - Professional AI Conversation Interface
 */

import { useState, useEffect, useRef, useCallback } from 'react'
import { useParams } from 'react-router-dom'
import { Spin, Empty, Drawer, Button, message } from 'antd'
import { CheckCircleOutlined, HistoryOutlined, PlusOutlined } from '@ant-design/icons'
import * as agentApi from '@/api/agent'
import { type Agent, type Citation, type Conversation, type Message, type SSEToolEvent } from '@/types/agent'
import { createStreamRequest } from '@/utils/streamRequest'
import {
  AgentInfo,
  ChatContainer,
  ChatInput,
  ConversationList,
} from '@/components/Chat'
import RouteHeader from '@/components/Layout/RouteHeader'
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

  const loadAgent = useCallback(async () => {
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
  }, [agentId])

  const loadConversations = useCallback(async () => {
    try {
      const { data } = await agentApi.listConversations(agentId || '', 1, 20)
      setConversations(data.items)
    } catch (error) {
      console.error('Failed to load conversations:', error)
    }
  }, [agentId])

  useEffect(() => {
    if (!agentId) return

    let cancelled = false
    queueMicrotask(() => {
      if (cancelled) return
      void loadAgent()
      void loadConversations()
    })

    return () => {
      cancelled = true
    }
  }, [agentId, loadAgent, loadConversations])

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
      tool_calls: [],
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
        onCitations: (incoming) => {
          // 一次对话里可能多次调用知识库工具，每次推送一批增量引用；
          // done 事件还会冗余推一次全量。统一按 marker 去重后排序，保证幂等。
          setMessages((prev) =>
            prev.map((msg) => {
              if (msg.id !== assistantMessageId) return msg
              const merged = new Map<number, Citation>()
              for (const item of msg.citations ?? []) merged.set(item.marker, item)
              for (const item of incoming) merged.set(item.marker, item)
              return {
                ...msg,
                citations: [...merged.values()].sort((a, b) => a.marker - b.marker),
              }
            })
          )
        },
        onToolStart: (event: SSEToolEvent) => {
          setMessages((prev) =>
            prev.map((msg) =>
              msg.id === assistantMessageId
                ? { ...msg, tool_calls: [...(msg.tool_calls ?? []), { ...event }] }
                : msg,
            ),
          )
        },
        onToolEnd: (event: SSEToolEvent) => {
          setMessages((prev) =>
            prev.map((msg) => {
              if (msg.id !== assistantMessageId) return msg
              const calls = [...(msg.tool_calls ?? [])]
              const index = calls.findIndex((call) => call.call_id === event.call_id)
              if (index === -1) calls.push({ ...event })
              else calls[index] = { ...calls[index], ...event }
              return { ...msg, tool_calls: calls }
            }),
          )
        },
        onToolError: (event: SSEToolEvent) => {
          setMessages((prev) =>
            prev.map((msg) => {
              if (msg.id !== assistantMessageId) return msg
              const calls = [...(msg.tool_calls ?? [])]
              const index = calls.findIndex((call) => call.call_id === event.call_id)
              if (index === -1) calls.push({ ...event })
              else calls[index] = { ...calls[index], ...event }
              return { ...msg, tool_calls: calls }
            }),
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
        onError: (error, errorCode) => {
          // 保留占位符的消息槽位：如果错误发生在工具执行之后，工具轨迹不能
          // 因错误而消失，否则用户看不到 Agent 在哪里失败。
          setMessages((prev) =>
            prev.map((msg) =>
              msg.id === assistantMessageId
                ? { ...msg, content: error, is_error: true, error_code: errorCode }
                : msg,
            ),
          )
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

  const starterPrompts = [
    '帮我梳理这份材料的重点',
    '把这个目标拆成执行步骤',
    '根据知识库回答一个问题',
  ]

  if (loading) {
    return (
      <div className="agent-chat-container">
        <RouteHeader
          compact
          title="Agent 对话"
          description="正在连接 Agent"
          backTo="/agents"
          backLabel="返回 Agent 列表"
        />
        <div className="flex items-center justify-center flex-1 p-6">
          <Spin size="large" />
        </div>
      </div>
    )
  }

  if (!agent) {
    return (
      <div className="agent-chat-container">
        <RouteHeader
          compact
          title="Agent 对话"
          description="Agent 工作台"
          backTo="/agents"
          backLabel="返回 Agent 列表"
        />
        <div className="flex items-center justify-center flex-1 p-6">
          <Empty description="Agent不存在" />
        </div>
      </div>
    )
  }

  return (
    <div className="agent-chat-container">
      <RouteHeader
        compact
        title="Agent 对话"
        description={agent.name}
        backTo="/agents"
        backLabel="返回 Agent 列表"
      />
      <div className="chat-workspace">
        <aside className="conversation-sidebar" aria-label="对话历史">
          <div className="conversation-sidebar__header">
            <div>
              <span className="conversation-sidebar__eyebrow">工作会话</span>
              <strong>任务记录</strong>
            </div>
            <Button
              type="text"
              icon={<PlusOutlined />}
              aria-label="新建对话"
              onClick={handleCreateNewConversation}
            />
          </div>
          <ConversationList
            conversations={conversations}
            currentConversationId={currentConversation?.id}
            onSelect={handleSelectConversation}
            onCreateNew={handleCreateNewConversation}
            showCreateButton={false}
          />
        </aside>

        <main className="chat-main">
          {/* 智能状态线：只作为工作状态信号，不把整页做成装饰性渐变。 */}
          <div className="intelligence-bar" />
          <div className="chat-main__header">
            <div className="chat-main__session">
              <span className="chat-main__session-label">当前任务</span>
              <strong>{currentConversation?.title || '新对话'}</strong>
            </div>
            <div className="chat-main__header-actions">
              <span className={`chat-runtime-status ${isStreaming ? 'chat-runtime-status--active' : ''}`}>
                <CheckCircleOutlined />
                {isStreaming ? 'Agent 执行中' : 'Agent 就绪'}
              </span>
              <Button
                type="text"
                className="history-toggle-button"
                icon={<HistoryOutlined />}
                onClick={() => setDrawerVisible(true)}
              >
                <span>历史会话</span>
              </Button>
            </div>
          </div>

          {/* Agent 信息区域 */}
          <div className="agent-info-wrapper">
            <AgentInfo agent={agent} />
          </div>

          {/* 消息列表区域 */}
          <div className="messages-wrapper">
            <ChatContainer
              messages={messages}
              isStreaming={isStreaming}
              agentName={agent.name}
              starterPrompts={starterPrompts}
              onStarterPrompt={handleSendMessage}
            />
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
        </main>
      </div>

      {/* 对话历史抽屉 */}
      <Drawer
        title="对话历史"
        className="chat-history-drawer"
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
          showCreateButton
        />
      </Drawer>
    </div>
  )
}
