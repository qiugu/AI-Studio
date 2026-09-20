import type { Citation } from '@/types/agent'
import { formatCitation } from '@/utils/citation'
import './Citation.css'

interface CitationBadgeProps {
  /** 角标编号（1 基，单轮内唯一） */
  marker: number
  /**
   * 对应的引用对象。缺失表示该角标在本轮引用列表中找不到来源
   * （模型编造了编号，或引用未随消息持久化），此时角标降级为纯文本。
   */
  citation?: Citation
  /** 提供时才可点击；由消息层决定是否挂载来源面板 */
  onCitationClick?: (marker: number) => void
}

/** 悬浮提示：「《手册.pdf》 · 第 37–38 页 · §3.2」 */
function buildTooltip(citation: Citation | undefined): string | undefined {
  if (!citation) return undefined
  const source = formatCitation(citation)
  return [citation.doc_name, source].filter(Boolean).join(' · ')
}

/**
 * 编号在本轮引用列表里查不到时（模型幻觉/编号写错），退回纯文本。
 *
 * 不能渲染成同款蓝色角标：那等于给一个没有来源的编号盖上「已溯源」的印章，
 * 比不加标记更有误导性。
 */
function UnresolvedMarker({ marker }: { marker: number }) {
  return <>[{marker}]</>
}

/**
 * 只呈现编号、不带交互的角标。
 *
 * 用于知识库检索页：那里的编号是**响应内编号**，与对话里的**轮次内编号**不同源，
 * 但视觉必须一致——否则用户会把它当成两种不同的东西，反而更难理解。
 */
export function CitationMarker({ marker, title }: { marker: number; title?: string }) {
  return (
    <span className="citation-badge" title={title}>
      {`[${marker}]`}
    </span>
  )
}

/**
 * 引用角标 `[n]`。
 *
 * 用 `<button>` 而不是 `<span onClick>`：键盘可达、可聚焦、默认带按钮语义，
 * 无需手动补 `role` 与 `tabIndex`。不可点击（无来源）时退回 `<span>`，
 * 避免把一个点不动的按钮暴露给读屏软件。
 */
export default function CitationBadge({ marker, citation, onCitationClick }: CitationBadgeProps) {
  const label = `[${marker}]`
  const tooltip = buildTooltip(citation) ?? '引用来源不可用'
  const className = `citation-badge${citation && onCitationClick ? ' citation-badge-clickable' : ''}`

  if (!citation) return <UnresolvedMarker marker={marker} />

  // 有来源但没接回调（如 Prompt 预览里复用渲染器）：保持角标样式，只是不可点
  if (!onCitationClick) {
    return (
      <span className={className} title={tooltip}>
        {label}
      </span>
    )
  }

  return (
    <button
      type="button"
      className={className}
      title={tooltip}
      aria-label={`查看引用 ${marker} 的来源：${tooltip}`}
      onClick={(event) => {
        // 阻止冒泡：消息气泡上若将来挂载其它点击处理，不应连带触发
        event.stopPropagation()
        onCitationClick(marker)
      }}
    >
      {label}
    </button>
  )
}
