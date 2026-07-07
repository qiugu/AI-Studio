/**
 * Markdown 渲染组件 - 支持代码高亮和 GitHub 风格 Markdown
 */

import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeHighlight from 'rehype-highlight'
import rehypeRaw from 'rehype-raw'
import 'highlight.js/styles/github-dark.css'
import './MarkdownRenderer.css'

interface MarkdownRendererProps {
  content: string
  className?: string
}

/**
 * Markdown 渲染器
 * 支持 GFM (GitHub Flavored Markdown)、代码高亮、HTML 标签
 */
export default function MarkdownRenderer({ content, className }: MarkdownRendererProps) {
  return (
    <div className={`markdown-body ${className || ''}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeHighlight, rehypeRaw]}
        components={{
          // 自定义代码块渲染
          code({ className, children, ...props }) {
            const match = /language-(\w+)/.exec(className || '')
            const isInline = !match
            
            if (isInline) {
              return (
                <code className="inline-code" {...props}>
                  {children}
                </code>
              )
            }
            
            return (
              <code className={className} {...props}>
                {children}
              </code>
            )
          },
          // 自定义链接渲染（新窗口打开）
          a({ href, children, ...props }) {
            return (
              <a href={href} target="_blank" rel="noopener noreferrer" {...props}>
                {children}
              </a>
            )
          },
          // 自定义表格渲染
          table({ children }) {
            return (
              <div className="table-wrapper">
                <table>{children}</table>
              </div>
            )
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  )
}