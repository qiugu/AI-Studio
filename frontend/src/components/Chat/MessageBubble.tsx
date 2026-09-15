import { UserOutlined, RobotOutlined } from '@ant-design/icons'
import MarkdownRenderer from '../MarkdownRenderer'
import type { Message } from '@/types/agent'

interface MessageBubbleProps {
  message: Message
  isStreaming?: boolean
}

/**
 * 错误标题按 error_code 区分。
 *
 * 此前无论什么错误都硬编码成「模型调用失败」，会把**没走到模型**的失败
 * （如工具装配失败、认证失败、限流）也归咎于模型，引导用户去查 API Key 而
 * 实际原因在别处。未识别的错误码退化为中性措辞。
 */
const ERROR_TITLES: Record<string, string> = {
  AGENT_ASSEMBLY_ERROR: '智能体执行失败',
  AUTHENTICATION_ERROR: 'API 认证失败',
  RATE_LIMIT_ERROR: '调用频率超限',
  CONTEXT_LENGTH_EXCEEDED: '输入超出上下文长度',
  CONTENT_FILTER_ERROR: '内容审核未通过',
  CONNECTION_ERROR: '网络连接失败',
  SERVICE_CONNECTION_ERROR: '无法连接模型服务',
  API_STATUS_ERROR: '模型服务异常',
  OLLAMA_NOT_FOUND_ERROR: '模型或端点不存在',
  SYSTEM_ERROR: '系统内部错误',
  UNKNOWN_ERROR: '执行失败',
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
    const title = ERROR_TITLES[message.error_code ?? ''] ?? '执行失败'
    return (
      <div className="message-wrapper">
        <div className="message-avatar ai">
          <RobotOutlined />
        </div>
        <div className="message-content-wrapper">
          <div className="message-content error">
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
              <span style={{ fontSize: '16px' }}>⚠️</span>
              <span style={{ fontWeight: 600 }}>{title}</span>
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