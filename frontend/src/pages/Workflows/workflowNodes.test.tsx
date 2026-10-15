// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'

import { getLoopHandleDefinitions } from './workflowLoopHandles'

describe('循环节点连接语义', () => {
  it('提供面向用户的循环体和完成后连接桩标识', () => {
    expect(getLoopHandleDefinitions()).toEqual([
      { id: 'loop-body', position: 'right', label: '循环体' },
      { id: 'loop-done', position: 'bottom', label: '完成后' },
    ])
  })
})
