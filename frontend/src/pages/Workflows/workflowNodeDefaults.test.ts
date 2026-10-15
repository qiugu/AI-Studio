import { describe, expect, it } from 'vitest'

import {
  getDefaultNodeConfig,
  getDefaultNodeName,
  normalizeLoopSourceHandle,
} from './workflowNodeDefaults'

describe('工作流节点默认值', () => {
  it('新建循环节点直接提供可理解的遍历配置', () => {
    expect(getDefaultNodeName('loop')).toBe('遍历集合')
    expect(getDefaultNodeConfig('loop')).toEqual({
      loop_type: 'for',
      loop_source: 'items',
      loop_variable: 'item',
      max_iterations: 100,
    })
  })

  it('打开旧工作流时把位置型出口映射为语义出口', () => {
    expect(normalizeLoopSourceHandle('source-right')).toBe('loop-body')
    expect(normalizeLoopSourceHandle('source-bottom')).toBe('loop-done')
    expect(normalizeLoopSourceHandle('loop-body')).toBe('loop-body')
  })
})
