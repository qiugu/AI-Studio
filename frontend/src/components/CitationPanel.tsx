import { useEffect, useRef } from 'react'
import { Drawer, Empty, Tag } from 'antd'
import type { Citation } from '@/types/agent'
import { formatCitation } from '@/utils/citation'
import { isStructuredChunk } from '@/utils/chunkType'
import ChunkContentView from './ChunkContentView'
import './Citation.css'

interface CitationPanelProps {
  open: boolean
  onClose: () => void
  /** 本轮消息命中的全部引用，按 marker 升序 */
  citations: Citation[]
  /** 被点击的角标编号，用于滚动定位与高亮；为 null 时展示列表顶部 */
  activeMarker?: number | null
}

/**
 * 引用来源抽屉。
 *
 * 展示的是**引用对象自带的原文快照**（`content`），不是回查数据库得到的分块全文。
 * 这一点很关键：知识库重新分块后，旧块的 `chunk_id` 可能已不存在，但用户看到的
 * 历史回答仍应能溯源——快照让溯源能力不依赖分块的生命周期（见方案 R1）。
 */
export default function CitationPanel({
  open,
  onClose,
  citations,
  activeMarker = null,
}: CitationPanelProps) {
  const itemRefs = useRef<Map<number, HTMLDivElement | null>>(new Map())

  // 打开时把被点击的角标滚进视野。用 rAF 而非直接调用：antd Drawer 首次打开
  // 时才挂载子节点，effect 执行时目标节点可能尚未进入 DOM。
  useEffect(() => {
    if (!open || activeMarker == null) return

    const frame = requestAnimationFrame(() => {
      const target = itemRefs.current.get(activeMarker)
      // 定位纯属锦上添花：jsdom 与个别旧环境没有 scrollIntoView，
      // 缺失时必须静默跳过，不能让「滚不动」把整个抽屉拖崩。
      if (target && typeof target.scrollIntoView === 'function') {
        target.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
      }
    })
    return () => cancelAnimationFrame(frame)
  }, [open, activeMarker])

  return (
    <Drawer
      title={`引用来源（${citations.length}）`}
      placement="right"
      size={480}
      open={open}
      onClose={onClose}
      className="citation-drawer"
    >
      {citations.length === 0 ? (
        <Empty description="本轮没有可溯源的引用" />
      ) : (
        <div className="citation-list">
          {citations.map((item) => {
            const source = formatCitation(item)
            const isActive = activeMarker != null && item.marker === activeMarker

            return (
              <div
                key={item.marker}
                ref={(el) => {
                  itemRefs.current.set(item.marker, el)
                }}
                className={`citation-item${isActive ? ' citation-item-active' : ''}`}
              >
                <div className="citation-item-head">
                  <span className="citation-item-marker">[{item.marker}]</span>
                  <span className="citation-item-doc" title={item.doc_name}>
                    {item.doc_name}
                  </span>
                </div>

                <div className="citation-item-meta">
                  {source ? <span>{source}</span> : null}
                  {item.chunk_index != null ? <span>块 #{item.chunk_index}</span> : null}
                  {item.score != null ? (
                    <span className="citation-item-score">相关度 {item.score.toFixed(3)}</span>
                  ) : null}
                </div>

                {/* 原文快照。表格/代码按类型渲染——纯文本输出会丢掉表的行列结构与
                    代码的缩进；其余类型仍用 `pre` 输出：它需要的是**精确换行**与等宽
                    字形，而这两点正是 `<pre>` 的语义，改用 `div` 会连字体一起变掉。
                    历史引用对象没有 `chunk_type`，`isStructuredChunk(undefined)` 为
                    false，自然落到 `pre` 分支。 */}
                {isStructuredChunk(item.chunk_type) ? (
                  <ChunkContentView
                    content={item.content}
                    chunkType={item.chunk_type}
                    className="citation-item-content citation-item-structured"
                  />
                ) : (
                  <pre className="citation-item-content">{item.content}</pre>
                )}

                {item.content_truncated ? (
                  <div className="citation-item-note">
                    <Tag color="orange">片段已截断</Tag>
                    <span>因本轮命中数量较多，此处仅展示原文开头部分。</span>
                  </div>
                ) : null}

                {item.context_expanded ? (
                  <div className="citation-item-note">
                    <Tag>上下文已扩展</Tag>
                    <span>模型看到的上下文比此片段更宽（含相邻块）。</span>
                  </div>
                ) : null}

                {item.query ? (
                  <div className="citation-item-query">召回查询：{item.query}</div>
                ) : null}
              </div>
            )
          })}
        </div>
      )}
    </Drawer>
  )
}
