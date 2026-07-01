import { useEffect, useRef } from 'react'
import { Alert } from 'antd'
import MessageBubble from './MessageBubble'
import type { Message } from '@/types/agent'

interface ChatContainerProps {
  messages: Message[]
  isStreaming?: boolean
}

export default function ChatContainer({ messages, isStreaming = false }: ChatContainerProps) {
  const containerRef = useRef<HTMLDivElement>(null)

  // 自动滚动到底部
  useEffect(() => {
    if (containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight
    }
  }, [messages])

  // 分离错误消息和正常消息
  const errorMessages = messages.filter((msg) => msg.is_error)
  const normalMessages = messages.filter((msg) => !msg.is_error)

  return (
    <div ref={containerRef} className="messages-container">
      {/* 错误消息列表 */}
      {errorMessages.length > 0 && (
        <div style={{ marginBottom: '16px' }}>
          {errorMessages.map((msg) => (
            <Alert
              key={msg.id}
              type="error"
              message="模型调用失败"
              description={msg.content}
              showIcon
              style={{ marginBottom: '12px' }}
            />
          ))}
        </div>
      )}

      {/* 正常消息列表 */}
      {normalMessages.length === 0 ? (
        <div className="messages-empty">
          <div className="messages-empty-icon">💬</div>
          <div className="messages-empty-text">开始新对话</div>
          <div className="messages-empty-hint">输入消息开始与 AI 交流</div>
        </div>
      ) : (
        <div>
          {normalMessages.map((msg, index) => (
            <MessageBubble
              key={msg.id}
              message={msg}
              isStreaming={isStreaming && index === normalMessages.length - 1 && msg.role === 'assistant'}
            />
          ))}
        </div>
      )}
    </div>
  )
}