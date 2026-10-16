import { CodeOutlined, FormatPainterOutlined, QuestionCircleOutlined } from '@ant-design/icons'
import { Button, Space, Tooltip, Typography } from 'antd'
import type { ReactNode } from 'react'

import CodeEditor from './CodeEditor'

interface JsonEditorProps {
  id?: string
  label?: ReactNode
  tooltip?: string
  placeholder?: string
  example?: string
  value?: string
  onChange?: (value: string) => void
  height?: string | number
  allowEmpty?: boolean
}

function getJsonType(value: unknown) {
  if (Array.isArray(value)) return '数组'
  if (value === null) return '空值'
  if (typeof value === 'object') return '对象'
  if (typeof value === 'string') return '字符串'
  if (typeof value === 'number') return '数字'
  if (typeof value === 'boolean') return '布尔值'
  return 'JSON'
}

function parseJson(value: string, allowEmpty: boolean) {
  if (!value.trim()) {
    return allowEmpty ? { value: null, error: null } : { value: null, error: '内容不能为空' }
  }

  try {
    return { value: JSON.parse(value) as unknown, error: null }
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error)
    return { value: null, error: `JSON 语法错误：${detail}` }
  }
}

function formatJsonHint(value?: string) {
  if (!value) return ''
  try {
    return JSON.stringify(JSON.parse(value), null, 2)
  } catch {
    return value
  }
}

export default function JsonEditor({
  id,
  label,
  tooltip,
  placeholder,
  example,
  value = '',
  onChange,
  height = 180,
  allowEmpty = true,
}: JsonEditorProps) {
  const parsed = parseJson(value, allowEmpty)
  const hasContent = Boolean(value.trim())
  const hasError = Boolean(parsed.error)
  const emptyHint = formatJsonHint(example ?? placeholder)

  const handleFormat = () => {
    if (hasError || !hasContent) return
    onChange?.(JSON.stringify(parsed.value, null, 2))
  }

  return (
    <div className={`json-editor${hasError ? ' json-editor--error' : ''}`}>
      <div className="json-editor__heading">
        <span className="json-editor__label">
          {label ?? 'JSON'}
          {tooltip && (
            <Tooltip title={tooltip}>
              <QuestionCircleOutlined aria-label={`${String(label ?? 'JSON')}说明`} />
            </Tooltip>
          )}
        </span>
        <Space size={4}>
          <Button
            type="text"
            size="small"
            icon={<FormatPainterOutlined />}
            disabled={hasError || !hasContent}
            onClick={handleFormat}
            aria-label="格式化 JSON"
          >
            格式化
          </Button>
          {example && (
            <Button
              type="text"
              size="small"
              icon={<CodeOutlined />}
              onClick={() => onChange?.(example)}
              aria-label="填入示例"
            >
              填入示例
            </Button>
          )}
        </Space>
      </div>
      <div className="json-editor__surface">
        <CodeEditor
          id={id}
          value={value}
          onChange={onChange}
          language="json"
          height={height}
        />
        {!hasContent && emptyHint && (
          <span className="json-editor__placeholder" role="note" aria-label="JSON 示例">
            {emptyHint}
          </span>
        )}
      </div>
      <div className="json-editor__footer" aria-live="polite">
        {parsed.error ? (
          <Typography.Text type="danger">{parsed.error}</Typography.Text>
        ) : hasContent ? (
          <Typography.Text type="secondary">JSON 有效 · {getJsonType(parsed.value)}</Typography.Text>
        ) : (
          <Typography.Text type="secondary">
            {allowEmpty ? '可以留空；填写后会实时检查 JSON 格式' : '请输入合法的 JSON'}
          </Typography.Text>
        )}
      </div>
    </div>
  )
}
