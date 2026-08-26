import { UserOutlined, RobotOutlined } from '@ant-design/icons'
import MarkdownRenderer from '../MarkdownRenderer'
import type { Message } from '@/types/agent'

interface MessageBubbleProps {
  message: Message
  isStreaming?: boolean
}

export default function MessageBubble({ message, isStreaming = false }: MessageBubbleProps) {
  const isUser = message.role === 'user'
  const isError = message.is_error

  // 用户消息样式
  if (isUser) {
    return (
      <div className={`message-wrapper ${isUser ? 'user' : ''}`}>
        <div className="message-avatar user">
          <UserOutlined />
        </div>
        <div className="message-content-wrapper">
          <div className="message-content user">
            <p style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{message.content}</p>
          </div>
        </div>
      </div>
    )
  }

  // 错误消息样式
  if (isError) {
    return (
      <div className="message-wrapper">
        <div className="message-avatar ai">
          <RobotOutlined />
        </div>
        <div className="message-content-wrapper">
          <div className="message-content error">
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
              <span style={{ fontSize: '16px' }}>⚠️</span>
              <span style={{ fontWeight: 600 }}>模型调用失败</span>
            </div>
            <p style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontSize: '13px' }}>
              {message.content}
            </p>
          </div>
        </div>
      </div>
    )
  }

  // AI 消息样式
  return (
    <div className="message-wrapper">
      <div className="message-avatar ai">
        <RobotOutlined />
      </div>
      <div className="message-content-wrapper">
        <div className="message-content ai">
          {isStreaming && !message.content ? (
            <div className="streaming-indicator">
              <div className="streaming-dots">
                <div className="streaming-dot" />
                <div className="streaming-dot" />
                <div className="streaming-dot" />
              </div>
              <span>正在思考...</span>
            </div>
          ) : isStreaming ? (
            // 流式输出阶段使用纯文本渲染，避免逐字解析 Markdown 造成的性能开销与光标抖动，
            // 保证“打字机”效果平滑流畅；流结束后再由 MarkdownRenderer 渲染最终内容。
            <p style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', margin: 0 }}>
              {message.content}
            </p>
          ) : (
            <MarkdownRenderer content={message.content || ''} />
          )}
        </div>
      </div>
    </div>
  )
}