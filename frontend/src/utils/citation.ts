/**
 * 分块出处（citation）的呈现规则。
 *
 * 为什么需要单独一层：出处从「单值」升级为「区间 + 粗化标记」之后，页面里出现了
 * 三处各自拼字符串的诱惑（分块抽屉、检索结果、将来的引用角标）。而区间与粗化各带一个
 * 容易踩错的边界条件：
 *
 * 1. **单值只能表达起点**。块可以跨页（结构组合并的必然结果），只显示「第 37 页」
 *    而块内含有第 38 页的内容，是**沉默的错答**——读者无法察觉自己拿到了不完整的
 *    出处。故必须显示为「第 37–38 页」。
 * 2. **标题路径可能是粗化的**。合并兄弟子节 `A > B` 与 `A > C` 时只能标注公共祖先
 *    `A`，块内并没有 `A` 自身的内容。此时若照直显示「§A」，就是在断言一个不存在的
 *    出处。`heading_path_mixed` 为真时必须显示成「§A 等小节」。
 *
 * 另一个历史坑：原实现写作 `chunk.source_page ? \`第 ${...} 页\` : ''`——用真值判断
 * 而非空值判断。页码是 1 基，0 不会出现，所以尚未出过事故；但同样的写法用在
 * `chunk_index` 上就会把第 0 块判成「无序号」。本模块统一用 `== null` 判断。
 */

/** 出处字段的最小结构（结构体兼容，便于直接传入后端响应对象） */
export interface CitationSource {
  source_page?: number | null
  source_page_end?: number | null
  heading_path?: string | null
  heading_path_mixed?: boolean | null
}

/** 页码范围分隔符。用 U+2013 而不是连字符：连字符会被读成「第 37 到 38」的减号语义 */
const PAGE_RANGE_DASH = '–'

/**
 * 页码范围标签。
 *
 * - 无起始页 → `null`（非 PDF 格式本就没有页码，不该显示占位符）
 * - 结束页缺失或与起始页相同 → 「第 37 页」
 * - 否则 → 「第 37–38 页」（倒序输入会被纠正，避免出现「第 38–37 页」）
 */
export function formatPageRange(source: CitationSource): string | null {
  const start = source.source_page
  if (start == null) return null

  const end = source.source_page_end
  if (end == null || end === start) return `第 ${start} 页`

  const low = Math.min(start, end)
  const high = Math.max(start, end)
  return `第 ${low}${PAGE_RANGE_DASH}${high} 页`
}

/**
 * 标题路径标签。
 *
 * 粗化时追加「等小节」：告诉读者标注只是**共同祖先**，块内并不包含祖先自身的内容。
 */
export function formatHeadingPath(source: CitationSource): string | null {
  const path = source.heading_path
  if (!path) return null
  return source.heading_path_mixed ? `§${path} 等小节` : `§${path}`
}

/**
 * 完整出处标签：「第 37–38 页 · §A 等小节」。
 *
 * 两者都不可得时返回 `null`（而不是空字符串），让调用方显式决定不渲染，
 * 以免留下一个孤零零的分隔符。
 */
export function formatCitation(source: CitationSource): string | null {
  const parts = [formatPageRange(source), formatHeadingPath(source)].filter(
    (part): part is string => part !== null,
  )
  return parts.length > 0 ? parts.join(' · ') : null
}
