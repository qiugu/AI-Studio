/**
 * 分块内容视图：按**块类型**选择渲染方式。
 *
 * 背景：分块抽屉与检索结果此前都用 `whiteSpace: pre-wrap` 做纯文本渲染，于是解析层
 * 产出的 GFM 管道表在界面上显示为「一堆竖线」的纯文本。项目里已有支持 GFM 表格的
 * `MarkdownRenderer`（含 `.table-wrapper`），此前只用在对话气泡。
 *
 * 三类分支各自解决一个具体问题：
 *
 * | `chunkType` | 渲染 | 原因 |
 * |---|---|---|
 * | `table` | `MarkdownRenderer`（预览态折叠） | 表格的**结构本身就是信息**，纯文本下不可读 |
 * | `code`  | 加围栏后交 `MarkdownRenderer` | 解析层产出的代码是**裸文本**（不含 ```），不包围栏会被当成普通段落，等宽样式与换行语义全丢 |
 * | 其余    | 纯文本（`pre-wrap`） | 本来就是连续文本，交 Markdown 只会把 `#`、`*` 这类字符误解释成语法 |
 *
 * 第三类**刻意不走 Markdown**：`text` / `title` 块的内容里出现 `#`、`1.`、`*` 都是
 * 正常字符而非语法，用 Markdown 渲染会把它们吃掉或变形。修一个类型的显示缺陷，
 * 不该顺带改掉所有类型的排版。
 */

import { useState } from 'react'
import { Button } from 'antd'
import MarkdownRenderer from './MarkdownRenderer'
import './ChunkContentView.css'

interface ChunkContentViewProps {
  content: string
  /**
   * 块类型（后端 `chunk_type`：`text` / `table` / `code` / `title` / `image`）。
   * 缺省或未知一律按正文处理——不必要求调用方先做合法性判断。
   */
  chunkType?: string | null
  /**
   * 预览模式下的字符上限。**不传 = 完整渲染**。
   * 表格块忽略该值并改为折叠展示（截断后的表格不承载任何结构信息）。
   */
  previewChars?: number
  className?: string
}

/**
 * 把块内容转成可渲染的 Markdown。
 *
 * 只有 `code` 需要变换：解析层的代码块是裸文本，必须显式包围栏。若内容里已有
 * 三反引号，则用四反引号作围栏（否则首个 ``` 会提前闭合）。
 */
function toMarkdown(content: string, chunkType?: string | null): string {
  if (chunkType !== 'code') return content
  const fence = content.includes('```') ? '````' : '```'
  return `${fence}\n${content}\n${fence}`
}

/**
 * 按**行**边界截断，返回截断结果与是否发生截断。
 *
 * 为什么不定长 `slice`：Markdown 是结构化的，从中间切开会产生未闭合的围栏、
 * 残缺的表格行，渲染出来比纯文本更糟。逐行累加可保证结构完整。
 *
 * 唯一的例外是**首行本身就超限**（长段落没有换行）：那时行边界不存在，只能在
 * 字符边界硬切——否则「预览」会输出一整块超长内容，等于没做预览。
 */
function truncateByLine(content: string, limit: number): { text: string; truncated: boolean } {
  if (content.length <= limit) return { text: content, truncated: false }

  let acc = ''
  for (const line of content.split('\n')) {
    if (!acc && line.length > limit) {
      return { text: line.slice(0, limit), truncated: true }
    }
    if (acc && acc.length + line.length + 1 > limit) break
    acc = acc ? `${acc}\n${line}` : line
  }
  return { text: acc, truncated: true }
}

/** 表格的结构摘要：行数 × 列数（首行是表头，第二行是分隔行） */
function tableSummary(content: string): string {
  const lines = content.split('\n')
  const rows = Math.max(lines.length - 2, 0)
  const cols = Math.max((lines[0]?.match(/\|/g)?.length ?? 1) - 1, 1)
  return `表格 ${rows} 行 × ${cols} 列`
}

/**
 * 表格的预览形态：默认**折叠**，按需展开。
 *
 * 折叠有两个理由：① 表格的行列数本身就是可展示的结构信息，展开前用户已能判断
 * 是否需要；② `MarkdownRenderer` 挂了 rehypeRaw / rehypeSanitize / rehypeHighlight，
 * 检索列表单页最多 20 条，全部展开渲染会明显拖慢列表。
 *
 * 折叠态**不渲染表格体**（而非用 CSS 隐藏）：20 张表的 DOM 与语法高亮开销都在
 * 展开时才付出，这才是折叠的性能意义。
 */
function TablePreview({ content }: { content: string }) {
  const [expanded, setExpanded] = useState(false)
  return (
    <div className="chunk-view-table">
      <div className="chunk-view-toolbar">
        <span className="chunk-view-summary">{tableSummary(content)}</span>
        <Button type="link" size="small" onClick={() => setExpanded((prev) => !prev)}>
          {expanded ? '收起' : '展开'}
        </Button>
      </div>
      {expanded ? <MarkdownRenderer content={content} /> : null}
    </div>
  )
}

export default function ChunkContentView({
  content,
  chunkType,
  previewChars,
  className,
}: ChunkContentViewProps) {
  // 表格块：预览模式下折叠；完整模式下直接渲染为真实 <table>
  if (chunkType === 'table') {
    return previewChars ? (
      <TablePreview content={content} />
    ) : (
      <MarkdownRenderer content={content} className={className} />
    )
  }

  const limit = previewChars && previewChars > 0 ? previewChars : null
  const { text, truncated } = limit
    ? truncateByLine(content, limit)
    : { text: content, truncated: false }

  if (chunkType === 'code') {
    return (
      <div className={className}>
        <MarkdownRenderer content={toMarkdown(text, chunkType)} />
        {truncated ? <span className="chunk-view-truncated">…</span> : null}
      </div>
    )
  }

  // 正文类（text / title / image / 未知）：纯文本原样输出，保留换行
  return (
    <div className={className} style={{ whiteSpace: 'pre-wrap' }}>
      {text}
      {truncated ? <span className="chunk-view-truncated">…</span> : null}
    </div>
  )
}
