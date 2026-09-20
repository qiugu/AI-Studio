/**
 * 引用角标 `[n]` 的 mdast 转换插件。
 *
 * 为什么在 AST 层做，而不是在字符串层做 `replace`：
 * 1. **代码块必须免疫**。模型常在示例里写 `[1]`（`arr[1]`、`[0]` 之类），
 *    字符串替换会把它们一并变成角标。mdast 里代码块是独立的 `code` /
 *    `inlineCode` 节点，其文本存在 `value` 而不是 `children`，因此
 *    遍历 `children` 天然跳不过去。
 * 2. **链接内的文本也不能再嵌链接**。`[1](https://x)` 已经是 `link` 节点，
 *    若在其内部再插入 `link` 会产生非法嵌套结构。
 *
 * 转换产物是一个 `link` 节点，`url` 为 `#cite-<n>` 形式的片段标识符。
 * 选择片段标识符而非自定义节点类型的原因：
 * - `rehype-sanitize` 的默认策略允许无协议（相对/片段）URL，无需放宽 XSS 白名单；
 * - `react-markdown` 默认的 `urlTransform` 对不含 `:` 的 URL 原样放行；
 * - 渲染层只需在 `components.a` 里按前缀识别，无需注册新节点渲染器。
 */

import type { Root } from 'mdast'

/** 角标链接的 href 前缀 */
export const CITATION_HREF_PREFIX = '#cite-'

/** 角标编号上限。防止模型输出的长数字串（如 `[12345]`）被误判为引用 */
const MAX_MARKER = 999

/** 匹配 `[n]`，n 为 1~3 位数字 */
const CITATION_PATTERN = /\[(\d{1,3})\]/g

/**
 * 这些节点内部不参与角标转换。
 *
 * `code` / `inlineCode` / `definition` 等节点的文本在 `value` 而非 `children`，
 * 本就不会被遍历到；真正需要显式排除的是 `link` / `linkReference` / `image`
 * ——否则会在链接内部再嵌一个链接。
 */
const OPAQUE_NODES = new Set([
  'link',
  'linkReference',
  'image',
  'imageReference',
  'footnoteReference',
  'definition',
  'footnoteDefinition',
])

/** 结构上够用的 mdast 节点视图。避免为每种节点类型写窄化的联合类型 */
interface MdastNode {
  type: string
  value?: string
  url?: string
  children?: MdastNode[]
}

/** 由角标编号生成 href */
export function buildCitationHref(marker: number): string {
  return `${CITATION_HREF_PREFIX}${marker}`
}

/**
 * 从 href 反解角标编号；非角标链接返回 `null`。
 * 用于渲染层区分「普通链接」与「引用角标」。
 */
export function parseCitationHref(href: string | undefined): number | null {
  if (!href || !href.startsWith(CITATION_HREF_PREFIX)) return null

  const raw = href.slice(CITATION_HREF_PREFIX.length)
  if (!/^\d+$/.test(raw)) return null

  const marker = Number(raw)
  return marker > 0 && marker <= MAX_MARKER ? marker : null
}

/**
 * 把一段纯文本里的 `[n]` 切分成「文本 / 角标链接 / 文本 ...」。
 * 无命中时返回 `null`，让调用方可以跳过重建子节点数组。
 */
function splitByCitations(value: string): MdastNode[] | null {
  CITATION_PATTERN.lastIndex = 0

  const parts: MdastNode[] = []
  let cursor = 0
  let match: RegExpExecArray | null
  let found = false

  while ((match = CITATION_PATTERN.exec(value)) !== null) {
    const marker = Number(match[1])
    if (marker < 1 || marker > MAX_MARKER) continue

    found = true

    if (match.index > cursor) {
      parts.push({ type: 'text', value: value.slice(cursor, match.index) })
    }

    parts.push({
      type: 'link',
      url: buildCitationHref(marker),
      children: [{ type: 'text', value: match[0] }],
    })

    cursor = match.index + match[0].length
  }

  if (!found) return null

  if (cursor < value.length) {
    parts.push({ type: 'text', value: value.slice(cursor) })
  }

  return parts
}

/** 递归重写：先重建当前层的 text 子节点，再下沉到非 OPAQUE 的子节点 */
function rewrite(node: MdastNode): void {
  const children = node.children
  if (!children || children.length === 0) return

  let changed = false
  const next: MdastNode[] = []

  for (const child of children) {
    if (child.type === 'text' && typeof child.value === 'string') {
      const parts = splitByCitations(child.value)
      if (parts) {
        next.push(...parts)
        changed = true
        continue
      }
    }
    next.push(child)
  }

  if (changed) node.children = next

  for (const child of next) {
    if (!OPAQUE_NODES.has(child.type)) rewrite(child)
  }
}

/**
 * remark 插件：把正文中的 `[n]` 转成 `#cite-n` 链接节点。
 *
 * 无引用（`citations` 为空）时不挂载本插件——既不产生无意义的 AST 变更，
 * 也避免历史消息里恰好像角标的文本被点亮。
 */
export function remarkCitations() {
  return (tree: Root) => {
    rewrite(tree as unknown as MdastNode)
  }
}
