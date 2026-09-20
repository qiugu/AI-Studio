import { describe, expect, it } from 'vitest'

import { formatCitation, formatHeadingPath, formatPageRange } from './citation'

describe('formatPageRange', () => {
  it('无起始页时返回 null（非 PDF 格式本就没有页码）', () => {
    expect(formatPageRange({})).toBeNull()
    expect(formatPageRange({ source_page: null, source_page_end: null })).toBeNull()
  })

  it('单页块只显示一页', () => {
    expect(formatPageRange({ source_page: 37, source_page_end: 37 })).toBe('第 37 页')
  })

  it('结束页缺失时退化为单页，不显示悬空的区间', () => {
    expect(formatPageRange({ source_page: 37 })).toBe('第 37 页')
    expect(formatPageRange({ source_page: 37, source_page_end: null })).toBe('第 37 页')
  })

  it('跨页块显示闭区间', () => {
    expect(formatPageRange({ source_page: 37, source_page_end: 38 })).toBe('第 37–38 页')
    expect(formatPageRange({ source_page: 37, source_page_end: 41 })).toBe('第 37–41 页')
  })

  it('倒序输入被纠正，不产出「第 38–37 页」', () => {
    expect(formatPageRange({ source_page: 38, source_page_end: 37 })).toBe('第 37–38 页')
  })

  it('页码为 0 视为有效值（用空值判断而非真值判断）', () => {
    // 页码是 1 基，0 在真实数据中不出现；此用例锁定「按空值判断」的写法，
    // 防止有人改回 `source.source_page ? ... : ...` 而把 0 判成缺失。
    expect(formatPageRange({ source_page: 0, source_page_end: 0 })).toBe('第 0 页')
  })
})

describe('formatHeadingPath', () => {
  it('无标题路径时返回 null（PDF 恒为 null）', () => {
    expect(formatHeadingPath({})).toBeNull()
    expect(formatHeadingPath({ heading_path: null })).toBeNull()
    expect(formatHeadingPath({ heading_path: '' })).toBeNull()
  })

  it('精确路径直接显示', () => {
    expect(formatHeadingPath({ heading_path: 'Phase 0 > 学习目标' })).toBe(
      '§Phase 0 > 学习目标',
    )
    expect(
      formatHeadingPath({ heading_path: 'Phase 0', heading_path_mixed: false }),
    ).toBe('§Phase 0')
  })

  it('粗化路径追加「等小节」，避免断言一个块内并不存在的出处', () => {
    expect(formatHeadingPath({ heading_path: 'A', heading_path_mixed: true })).toBe(
      '§A 等小节',
    )
  })

  it('mixed 为 null/undefined 时按精确处理（三态不引入第三种呈现）', () => {
    expect(formatHeadingPath({ heading_path: 'A', heading_path_mixed: null })).toBe('§A')
  })
})

describe('formatCitation', () => {
  it('两者都不可得时返回 null，而不是空字符串', () => {
    expect(formatCitation({})).toBeNull()
  })

  it('只有页码时不留下悬空分隔符', () => {
    expect(formatCitation({ source_page: 37, source_page_end: 38 })).toBe('第 37–38 页')
  })

  it('只有标题时不留下悬空分隔符', () => {
    expect(formatCitation({ heading_path: 'A' })).toBe('§A')
  })

  it('两者都有时用 · 连接', () => {
    expect(
      formatCitation({
        source_page: 37,
        source_page_end: 38,
        heading_path: 'A',
        heading_path_mixed: true,
      }),
    ).toBe('第 37–38 页 · §A 等小节')
  })
})
