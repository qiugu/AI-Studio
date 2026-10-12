import { useEffect, useRef } from 'react'
import { ArrowUpOutlined, RobotOutlined } from '@ant-design/icons'
import MessageBubble from './MessageBubble'
import type { Message } from '@/types/agent'

interface ChatContainerProps {
  messages: Message[]
  isStreaming?: boolean
  agentName?: string
  starterPrompts?: string[]
  onStarterPrompt?: (prompt: string) => void
}

export default function ChatContainer({
  messages,
  isStreaming = false,
  agentName = 'AI Agent',
  starterPrompts = [],
  onStarterPrompt,
}: ChatContainerProps) {
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
          <div className="messages-empty__brand" aria-hidden="true">
            <RobotOutlined />
            <span>AI Studio</span>
          </div>
          <h2>准备好开始工作了吗？</h2>
          <p>与{agentName}描述目标，Agent 会在这里完成推理与执行。</p>
          {onStarterPrompt && starterPrompts.length > 0 && (
            <div className="starter-prompts" aria-label="推荐任务">
              {starterPrompts.map((prompt) => (
                <button
                  key={prompt}
                  type="button"
                  className="starter-prompt"
                  onClick={() => onStarterPrompt(prompt)}
                >
                  <span>{prompt}</span>
                  <ArrowUpOutlined aria-hidden="true" />
                </button>
              ))}
            </div>
          )}
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
