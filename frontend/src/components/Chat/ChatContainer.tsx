import { useEffect, useRef } from 'react'
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

  return (
    <div ref={containerRef} className="messages-container">
      {messages.length === 0 ? (
        <div className="messages-empty">
          <div className="messages-empty-icon">💬</div>
          <div className="messages-empty-text">开始新对话</div>
          <div className="messages-empty-hint">输入消息开始与 AI 交流</div>
        </div>
      ) : (
        <div>
          {messages.map((msg, index) => (
            <MessageBubble
              key={msg.id}
              message={msg}
              // 流式光标只跟随最后一条助手消息；错误消息本身不是流式内容
              isStreaming={
                isStreaming &&
                index === messages.length - 1 &&
                msg.role === 'assistant' &&
                !msg.is_error
              }
            />
          ))}
        </div>
      )}
    </div>
  )
}
