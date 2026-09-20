import { describe, expect, it } from 'vitest'
import type { Root } from 'mdast'

import { buildCitationHref, parseCitationHref, remarkCitations } from './remarkCitations'

/**
 * 结构化的最小节点视图。
 *
 * mdast 的导出类型是精确的联合类型（`RootContent` 里 `Text` 没有 `children`），
 * 手写测试树时处处需要窄化；而本插件本身就是在宽松结构上工作的，
 * 测试用同样的宽松视图构造，反而不掩盖真实行为。
 */
interface TestNode {
  type: string
  value?: string
  url?: string
  children?: TestNode[]
}

function root(...children: TestNode[]): TestNode {
  return { type: 'root', children }
}

/** 跑一遍插件，返回变换后的树 */
function run(tree: TestNode): TestNode {
  remarkCitations()(tree as unknown as Root)
  return tree
}

describe('parseCitationHref', () => {
  it('从角标 href 反解编号', () => {
    expect(parseCitationHref(buildCitationHref(3))).toBe(3)
    expect(parseCitationHref('#cite-12')).toBe(12)
  })

  it('普通链接与非法输入返回 null，不会被误判成引用', () => {
    expect(parseCitationHref('https://example.com')).toBeNull()
    expect(parseCitationHref('/docs/cite-1')).toBeNull()
    expect(parseCitationHref('#cite-')).toBeNull()
    expect(parseCitationHref('#cite-abc')).toBeNull()
    expect(parseCitationHref(undefined)).toBeNull()
  })

  it('编号 0 与超范围值不被接受', () => {
    expect(parseCitationHref('#cite-0')).toBeNull()
    expect(parseCitationHref('#cite-1000')).toBeNull()
  })
})

describe('remarkCitations', () => {
  it('把 [n] 转成 #cite-n 链接节点，并保留前后文本', () => {
    const tree = run(
      root({
        type: 'paragraph',
        children: [{ type: 'text', value: '依据 [1] 与 [2] 可知。' }],
      })
    )
    const children = tree.children?.[0]?.children ?? []

    expect(children.map((node) => node.type)).toEqual([
      'text',
      'link',
      'text',
      'link',
      'text',
    ])
    expect(children[0]).toMatchObject({ value: '依据 ' })
    expect(children[1]).toMatchObject({ type: 'link', url: '#cite-1' })
    expect(children[3]).toMatchObject({ type: 'link', url: '#cite-2' })
    expect(children[4]).toMatchObject({ value: ' 可知。' })
  })

  it('角标链接的子节点是原始文本 [n]，渲染层据此显示角标', () => {
    const tree = run(root({ type: 'paragraph', children: [{ type: 'text', value: '见[7]' }] }))
    const link = tree.children?.[0]?.children?.[1]

    expect(link).toMatchObject({
      type: 'link',
      url: '#cite-7',
      children: [{ type: 'text', value: '[7]' }],
    })
  })

  it('无角标时不改动 AST（连子节点数组都不重建）', () => {
    const tree = root({
      type: 'paragraph',
      children: [{ type: 'text', value: '没有任何引用。' }],
    })
    const before = tree.children?.[0]?.children

    const after = run(tree).children?.[0]?.children

    expect(after).toBe(before)
  })

  it('代码块与行内代码免疫：示例里的 arr[1] 不会被点亮', () => {
    const tree = run(
      root(
        { type: 'code', value: 'const x = arr[1]' },
        { type: 'paragraph', children: [{ type: 'inlineCode', value: 'arr[1]' }] }
      )
    )

    expect(tree.children?.[0]).toMatchObject({ type: 'code', value: 'const x = arr[1]' })
    expect(tree.children?.[1]).toMatchObject({
      children: [{ type: 'inlineCode', value: 'arr[1]' }],
    })
  })

  it('不进入链接内部，避免生成嵌套链接', () => {
    const tree = run(
      root({
        type: 'paragraph',
        children: [
          {
            type: 'link',
            url: 'https://example.com/[1]',
            children: [{ type: 'text', value: '见 [1]' }],
          },
        ],
      })
    )
    const link = tree.children?.[0]?.children?.[0]

    expect(link?.type).toBe('link')
    expect(link?.children).toHaveLength(1)
    expect(link?.children?.[0]).toMatchObject({ type: 'text', value: '见 [1]' })
  })

  it('四位及以上数字不是角标（防止长数字串被误判）', () => {
    const tree = run(
      root({
        type: 'paragraph',
        children: [{ type: 'text', value: '共 [1234] 条，见 [2] 条' }],
      })
    )
    const children = tree.children?.[0]?.children ?? []
    const links = children.filter((node) => node.type === 'link')

    expect(links).toHaveLength(1)
    expect(links[0]).toMatchObject({ url: '#cite-2' })
  })

  it('递归处理列表等嵌套结构', () => {
    const tree = run(
      root({
        type: 'list',
        children: [
          {
            type: 'listItem',
            children: [
              { type: 'paragraph', children: [{ type: 'text', value: '条目 [1]' }] },
            ],
          },
        ],
      })
    )
    const paragraph = tree.children?.[0]?.children?.[0]?.children?.[0]

    expect(paragraph?.children?.[1]).toMatchObject({ type: 'link', url: '#cite-1' })
  })
})
