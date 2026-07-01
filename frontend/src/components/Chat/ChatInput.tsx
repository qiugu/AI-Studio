import { useState, useRef, useEffect } from 'react'
import { SendOutlined, StopOutlined } from '@ant-design/icons'

interface ChatInputProps {
  onSend: (message: string) => void
  onCancel?: () => void
  isLoading?: boolean
  placeholder?: string
  disabled?: boolean
}

export default function ChatInput({
  onSend,
  onCancel,
  isLoading = false,
  placeholder = '输入消息...',
  disabled = false,
}: ChatInputProps) {
  const [value, setValue] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  // 自动调整高度
  useEffect(() => {
    const textarea = textareaRef.current
    if (textarea) {
      textarea.style.height = 'auto'
      textarea.style.height = `${Math.min(textarea.scrollHeight, 200)}px`
    }
  }, [value])

  const handleSubmit = () => {
    if (!value.trim() || isLoading || disabled) return
    onSend(value.trim())
    setValue('')
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // Ctrl+Enter 或 Cmd+Enter 发送消息
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
      e.preventDefault()
      handleSubmit()
    }
  }

  return (
    <div className="input-container">
      <textarea
        ref={textareaRef}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        disabled={disabled || isLoading}
        className="input-textarea"
        style={{ minHeight: '24px', maxHeight: '200px' }}
        rows={1}
      />

      <div className="input-actions">
        {isLoading && onCancel ? (
          <button
            className="input-button stop"
            onClick={onCancel}
          >
            <StopOutlined />
            <span>停止</span>
          </button>
        ) : (
          <button
            className="input-button send"
            onClick={handleSubmit}
            disabled={!value.trim() || disabled || isLoading}
          >
            <SendOutlined />
            <span>发送</span>
          </button>
        )}
      </div>
    </div>
  )
}