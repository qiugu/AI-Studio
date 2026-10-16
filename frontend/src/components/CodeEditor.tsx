import Editor from '@monaco-editor/react'

interface Props {
  id?: string
  value: string
  onChange?: (value: string) => void
  language?: string
  height?: string | number
  readOnly?: boolean
}

export default function CodeEditor({
  id,
  value,
  onChange,
  language = 'markdown',
  height = 400,
  readOnly = false,
}: Props) {
  return (
    <Editor
      wrapperProps={id ? { id } : undefined}
      height={height}
      language={language}
      value={value}
      options={{
        minimap: { enabled: false },
        wordWrap: 'on',
        lineNumbers: 'on',
        scrollBeyondLastLine: false,
        readOnly,
        fontSize: 14,
      }}
      onChange={(v) => onChange?.(v ?? '')}
    />
  )
}
