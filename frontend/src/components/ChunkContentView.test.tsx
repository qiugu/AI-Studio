// @vitest-environment jsdom
/**
 * 分块内容视图的渲染回归（P2 前端接入）。
 *
 * 这里验证的是**用户实际看到什么**，因为本轮的原始报障就是显示层问题：解析层
 * 产出的 GFM 管道表在页面上显示成「一堆竖线」的纯文本。因此每条用例都断言具体
 * DOM 结构（`<table>` 存在与否、是否被当成标题），而不是哈希或快照——
 * 「渲染成了什么」是这一层唯一有意义的事实。
 *
 * 覆盖四类分支：`code` 补围栏、`table` 折叠/展开、正文类**不走 Markdown**、
 * 预览截断落在行边界。
 */
import { afterEach, describe, expect, it } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import ChunkContentView from './ChunkContentView'

// vitest 未开启 globals，RTL 的自动 cleanup 不会注册；跨用例残留的 DOM 会让
// 查询命中多个元素（antd 的 Drawer/Modal 挂在 body 上尤其明显）。显式清理。
afterEach(cleanup)

/** 一份 GFM 管道表分块的原文（解析层的 `table` 块就是这种文本） */
const TABLE = ['| 参数 | 默认值 |', '| --- | --- |', '| lr | 1e-4 |', '| batch | 32 |'].join(
  '\n'
)

describe('ChunkContentView 类型分支', () => {
  it('table 块渲染为真实 <table>，而不是一堆竖线', () => {
    const { container } = render(<ChunkContentView content={TABLE} chunkType="table" />)

    const table = container.querySelector('table')
    expect(table).toBeTruthy()
    // 表头单元格进入 <th>：这是「结构被识别」的证据，纯文本渲染时不存在
    const headers = Array.from(container.querySelectorAll('th')).map((el) => el.textContent)
    expect(headers).toEqual(['参数', '默认值'])
    expect(container.querySelectorAll('tbody tr')).toHaveLength(2)
  })

  it('table 块在预览态折叠，展开后才渲染表格体', () => {
    const { container } = render(
      <ChunkContentView content={TABLE} chunkType="table" previewChars={200} />
    )

    // 折叠态给出结构摘要（行列数本身就是信息）
    expect(screen.getByText('表格 2 行 × 2 列')).toBeTruthy()
    // 关键：折叠态**不渲染**表格体，20 条结果的列表不会一次性挂上 20 张表
    expect(container.querySelector('table')).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: '展开' }))
    expect(container.querySelector('table')).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: '收起' }))
    expect(container.querySelector('table')).toBeNull()
  })

  it('code 块补围栏后渲染为代码块，保留换行', () => {
    const code = 'def f(x):\n    return x + 1'
    const { container } = render(<ChunkContentView content={code} chunkType="code" />)

    const pre = container.querySelector('pre')
    expect(pre).toBeTruthy()
    expect(pre?.textContent).toContain('def f(x):')
    expect(pre?.textContent).toContain('    return x + 1')
    // 裸文本交给 remark 会被当段落；补围栏后必须落在 <code> 里
    expect(container.querySelector('pre code')).toBeTruthy()
  })

  it('内容含三反引号时用四反引号作围栏，避免提前闭合', () => {
    const code = '```\n内层围栏\n```'
    const { container } = render(<ChunkContentView content={code} chunkType="code" />)

    expect(container.querySelector('pre code')?.textContent).toContain('内层围栏')
  })

  it('正文类（text/title/未知）不走 Markdown：# 与 * 保持字面', () => {
    const text = '# 这不是标题\n* 这不是列表'
    const { container } = render(<ChunkContentView content={text} chunkType="text" />)

    expect(container.textContent).toContain('# 这不是标题')
    // 关键：没有 h1/ul —— 正文块里的 # 是普通字符，被解释成语法就是排版事故
    expect(container.querySelector('h1')).toBeNull()
    expect(container.querySelector('ul')).toBeNull()
  })

  it('正文类遇到管道表也不渲染成表格：类型来自 chunk_type，不靠内容猜测', () => {
    const { container } = render(<ChunkContentView content={TABLE} chunkType="text" />)

    // 刻意如此：从文本反推表格必然误判（正文里的 | 是常见字符），
    // 类型判断的唯一依据是后端解析层给出的 chunk_type
    expect(container.querySelector('table')).toBeNull()
  })

  it('缺省 chunkType 时按正文处理，不抛错', () => {
    const { container } = render(<ChunkContentView content="普通一段话" />)
    expect(container.textContent).toContain('普通一段话')
  })
})

describe('ChunkContentView 预览截断', () => {
  it('按行边界截断，不产生残缺表格行', () => {
    const long = `${TABLE}\n${'| 追加 | 值 |\n'.repeat(30)}`
    const { container } = render(
      <ChunkContentView content={long} chunkType="code" previewChars={60} />
    )

    // 截断标记出现，说明确实做了截断
    expect(container.querySelector('.chunk-view-truncated')).toBeTruthy()
    // 代码块仍闭合：截断没把围栏切掉（围栏由组件生成，截断只作用于内容）
    expect(container.querySelector('pre code')).toBeTruthy()
  })

  it('首行本身超限时退化为字符截断，否则预览等于没做', () => {
    const single = 'x'.repeat(1000)
    const { container } = render(<ChunkContentView content={single} previewChars={50} />)

    // 只截到 50 字符 + 一个省略号标记
    expect(container.textContent).toBe(`${'x'.repeat(50)}…`)
  })

  it('内容短于上限时不截断、不加省略号', () => {
    const { container } = render(<ChunkContentView content="短内容" previewChars={50} />)
    expect(container.textContent).toBe('短内容')
  })
})
