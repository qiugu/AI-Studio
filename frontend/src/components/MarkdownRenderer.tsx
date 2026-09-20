/**
 * Markdown 渲染组件 - 支持代码高亮和 GitHub 风格 Markdown
 */

import { useMemo } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeHighlight from 'rehype-highlight'
import rehypeRaw from 'rehype-raw'
import rehypeSanitize from 'rehype-sanitize'  // F1: 净化原始 HTML，防止 XSS（模型输出/Prompt 内容经 rehype-raw 注入）
import { parseCitationHref, remarkCitations } from '@/utils/remarkCitations'
import type { Citation } from '@/types/agent'
import CitationBadge from './CitationBadge'
import 'highlight.js/styles/github-dark.css'
import './MarkdownRenderer.css'

interface MarkdownRendererProps {
  content: string
  className?: string
  /**
   * 本条消息携带的引用列表。为空时不挂载角标插件，
   * 也不点亮正文里形如 `[1]` 的文本。
   */
  citations?: Citation[] | null
  /** 角标点击回调；不传时角标不可交互（如 Prompt 预览等无来源场景） */
  onCitationClick?: (marker: number) => void
}

/**
 * Markdown 渲染器
 * 支持 GFM (GitHub Flavored Markdown)、代码高亮、HTML 标签
 */
export default function MarkdownRenderer({
  content,
  className,
  citations,
  onCitationClick,
}: MarkdownRendererProps) {
  // marker → 引用。角标需要来源信息来渲染悬浮提示，并判断该编号是否真实存在。
  const citationMap = useMemo(() => {
    const map = new Map<number, Citation>()
    for (const item of citations ?? []) map.set(item.marker, item)
    return map
  }, [citations])

  const hasCitations = citationMap.size > 0

  // 仅在有引用时挂载角标插件：无引用时不改动 AST，也不点亮形似的文本。
  const remarkPlugins = useMemo(
    () => (hasCitations ? [remarkGfm, remarkCitations] : [remarkGfm]),
    [hasCitations]
  )

  return (
    <div className={`markdown-body ${className || ''}`}>
      <ReactMarkdown
        remarkPlugins={remarkPlugins}
        rehypePlugins={[rehypeHighlight, rehypeRaw, rehypeSanitize]}
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
          // 自定义链接渲染（新窗口打开）；引用角标由 AST 层转成 #cite-n 链接后在此截获
          a({ href, children, ...props }) {
            const marker = parseCitationHref(href)
            if (marker !== null) {
              return (
                <CitationBadge
                  marker={marker}
                  citation={citationMap.get(marker)}
                  onCitationClick={onCitationClick}
                />
              )
            }
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