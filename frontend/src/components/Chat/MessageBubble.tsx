import { useState } from 'react'
import { UserOutlined, RobotOutlined, CheckCircleOutlined, CloseCircleOutlined, LoadingOutlined, ToolOutlined } from '@ant-design/icons'
import MarkdownRenderer from '../MarkdownRenderer'
import CitationPanel from '../CitationPanel'
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
  PROVIDER_KEY_DECRYPT_ERROR: '供应商密钥无效',
  SYSTEM_ERROR: '系统内部错误',
  STREAM_INCOMPLETE: '响应流中断',
  UNKNOWN_ERROR: '执行失败',
}

function formatToolPayload(value: unknown): string {
  if (value === undefined || value === null) return ''
  if (typeof value === 'string') return value
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

function ToolTrace({ toolCalls }: { toolCalls: Array<Record<string, unknown>> }) {
  if (toolCalls.length === 0) return null

  return (
    <details className="tool-trace" open>
      <summary className="tool-trace__summary">
        <span className="tool-trace__title"><ToolOutlined /> 工具执行</span>
        <span className="tool-trace__count">{toolCalls.length} 次调用</span>
      </summary>
      <div className="tool-trace__list">
        {toolCalls.map((call, index) => {
          const status = call.status === 'error' ? 'error' : call.status === 'running' ? 'running' : 'success'
          const label = status === 'running' ? '执行中' : status === 'error' ? '失败' : '已完成'
          const toolName = call.tool || call.name
          const callInput = call.input ?? call.arguments
          return (
            <div className={`tool-trace__item tool-trace__item--${status}`} key={`${String(call.call_id || call.id || toolName)}-${index}`}>
              <div className="tool-trace__item-head">
                <span className="tool-trace__status" aria-label={label}>
                  {status === 'running' && <LoadingOutlined spin />}
                  {status === 'success' && <CheckCircleOutlined />}
                  {status === 'error' && <CloseCircleOutlined />}
                </span>
                <strong>{String(toolName || '未命名工具')}</strong>
                <span className="tool-trace__state">{label}</span>
              </div>
              {callInput !== undefined && (
                <div className="tool-trace__detail">
                  <span>输入</span>
                  <code>{formatToolPayload(callInput)}</code>
                </div>
              )}
              {call.output !== undefined && (
                <div className="tool-trace__detail">
                  <span>结果</span>
                  <code>{formatToolPayload(call.output)}</code>
                </div>
              )}
              {call.error !== undefined && (
                <div className="tool-trace__detail tool-trace__detail--error">
                  <span>错误</span>
                  <code>{formatToolPayload(call.error)}</code>
                </div>
              )}
            </div>
          )
        })}
      </div>
    </details>
  )
}

export default function MessageBubble({ message, isStreaming = false }: MessageBubbleProps) {
  const isUser = message.role === 'user'
  const isError = message.is_error

  // 来源面板的状态挂在消息级：同一屏里多条消息各自持有自己的抽屉，
  // 避免把「点开的是哪一条」上提到会话层再逐层回传 marker。
  const [activeCitation, setActiveCitation] = useState<number | null>(null)
  const citations = message.citations ?? null

  // 用户消息样式
  if (isUser) {
    return (
      <div className={`message-wrapper ${isUser ? 'user' : ''}`}>
        <div className="message-content-wrapper message-content-wrapper--user">
          <div className="message-meta message-meta--user">你</div>
          <div className="message-content user">
            <p style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{message.content}</p>
          </div>
        </div>
        <div className="message-avatar user">
          <UserOutlined />
        </div>
      </div>
    )
  }

  // 错误消息样式
  if (isError) {
    const title = ERROR_TITLES[message.error_code ?? ''] ?? '执行失败'
    return (
      <div className="message-wrapper message-wrapper--assistant">
        <div className="message-avatar ai">
          <RobotOutlined />
        </div>
        <div className="message-content-wrapper">
          <div className="message-meta">Agent</div>
          <ToolTrace toolCalls={message.tool_calls ?? []} />
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
    <div className="message-wrapper message-wrapper--assistant">
      <div className="message-avatar ai">
        <RobotOutlined />
      </div>
      <div className="message-content-wrapper">
        <div className="message-meta">Agent</div>
        <div className="message-content ai">
          <ToolTrace toolCalls={message.tool_calls ?? []} />
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
            <MarkdownRenderer
              content={message.content || ''}
              citations={citations}
              onCitationClick={setActiveCitation}
            />
          )}
        </div>

        {/* 只在确有引用时挂载抽屉：无引用时不渲染隐藏的 Drawer 节点 */}
        {citations && citations.length > 0 ? (
          <CitationPanel
            open={activeCitation !== null}
            onClose={() => setActiveCitation(null)}
            citations={citations}
            activeMarker={activeCitation}
          />
        ) : null}
      </div>
    </div>
  )
}
