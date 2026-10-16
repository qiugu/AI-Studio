// @vitest-environment jsdom
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import JsonEditor from './JsonEditor'

const codeEditorMock = vi.fn(
  ({ value, onChange }: { value: string; onChange?: (value: string) => void }) => (
    <textarea
      aria-label="json-code-editor"
      value={value}
      onChange={(event) => onChange?.(event.target.value)}
    />
  )
)

vi.mock('./CodeEditor', () => ({
  default: (props: {
    value: string
    onChange?: (value: string) => void
    language?: string
  }) => {
    codeEditorMock(props)
    return (
      <textarea
        aria-label="json-code-editor"
        value={props.value}
        onChange={(event) => props.onChange?.(event.target.value)}
      />
    )
  },
}))

describe('JsonEditor', () => {
  it('uses Monaco JSON mode and formats valid JSON', () => {
    const onChange = vi.fn()
    render(<JsonEditor label="高级配置" value='{"region":"cn-east"}' onChange={onChange} />)

    expect(codeEditorMock).toHaveBeenCalledWith(expect.objectContaining({ language: 'json' }))
    fireEvent.click(screen.getByRole('button', { name: '格式化 JSON' }))

    expect(onChange).toHaveBeenCalledWith('{\n  "region": "cn-east"\n}')
  })

  it('shows a validation error for invalid JSON and fills an example on request', () => {
    const onChange = vi.fn()
    render(
      <JsonEditor
        label="请求体"
        value='{"query":}'
        example={'{\n  "query": "北京天气"\n}'}
        onChange={onChange}
      />
    )

    expect(screen.getByText(/JSON 语法错误/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '填入示例' }))
    expect(onChange).toHaveBeenCalledWith('{\n  "query": "北京天气"\n}')
  })
})
