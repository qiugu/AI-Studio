/**
 * `isStructuredChunk` 的契约。
 *
 * 判据本身只有一行，但它是**两处消费方式的唯一交汇点**：渲染组件据此选渲染分支，
 * 引用面板据此选容器（`<pre>` 还是 `<div>`）。所以这里重点钉住「不该被判为结构化」
 * 的那些取值——尤其是 `undefined`：引用对象的历史快照没有 `chunk_type` 键，
 * 一旦被误判为结构化，历史引用会全部走进 Markdown 渲染分支。
 */

import { describe, expect, it } from 'vitest'
import { STRUCTURED_CHUNK_TYPES, isStructuredChunk } from './chunkType'

describe('isStructuredChunk', () => {
  it('table 与 code 需要类型化渲染', () => {
    expect(isStructuredChunk('table')).toBe(true)
    expect(isStructuredChunk('code')).toBe(true)
  })

  it('正文类与标题类不需要', () => {
    expect(isStructuredChunk('text')).toBe(false)
    expect(isStructuredChunk('title')).toBe(false)
    expect(isStructuredChunk('image')).toBe(false)
  })

  it('缺失或未知取值一律按正文处理', () => {
    // 历史引用对象没有该键：必须落到 <pre> 分支，而不是 Markdown 渲染
    expect(isStructuredChunk(undefined)).toBe(false)
    expect(isStructuredChunk(null)).toBe(false)
    expect(isStructuredChunk('')).toBe(false)
    expect(isStructuredChunk('something-new')).toBe(false)
  })

  it('判据与常量表同源，不各自硬编码', () => {
    // 反向守卫：新增结构化类型时必须改常量表，不能只在函数里加一个分支
    for (const chunkType of STRUCTURED_CHUNK_TYPES) {
      expect(isStructuredChunk(chunkType)).toBe(true)
    }
    expect(STRUCTURED_CHUNK_TYPES).toHaveLength(2)
  })
})
