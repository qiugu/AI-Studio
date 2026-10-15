import type { NodeType, WorkflowNodeConfig } from '../../types/workflow'

const defaultNodeNames: Partial<Record<NodeType, string>> = {
  loop: '遍历集合',
}

const defaultNodeConfigs: Partial<Record<NodeType, WorkflowNodeConfig>> = {
  loop: {
    loop_type: 'for',
    loop_source: 'items',
    loop_variable: 'item',
    max_iterations: 100,
  },
}

export const getDefaultNodeName = (nodeType: NodeType) =>
  defaultNodeNames[nodeType] ?? `新${nodeType}节点`

export const getDefaultNodeConfig = (nodeType: NodeType): WorkflowNodeConfig => ({
  ...(defaultNodeConfigs[nodeType] ?? {}),
})

export const normalizeLoopSourceHandle = (sourceHandle?: string | null) => {
  if (sourceHandle === 'source-right') return 'loop-body'
  if (sourceHandle === 'source-bottom') return 'loop-done'
  return sourceHandle ?? undefined
}
