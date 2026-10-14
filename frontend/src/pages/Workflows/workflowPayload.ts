import type { Edge, Node } from 'reactflow'

import type {
  NodeType,
  WorkflowEdgeCondition,
  WorkflowEdgeCreate,
  WorkflowNodeConfig,
  WorkflowNodeCreate,
} from '../../types/workflow'

export interface WorkflowGraphPayload {
  nodes: WorkflowNodeCreate[]
  edges: WorkflowEdgeCreate[]
}

/** 将 React Flow 运行态数据收敛成后端整图替换契约。 */
export function buildWorkflowGraphPayload(nodes: Node[], edges: Edge[]): WorkflowGraphPayload {
  return {
    nodes: nodes.map((node) => ({
      temp_id: node.id,
      node_type: node.type as NodeType,
      name: node.data.name,
      position_x: node.position.x,
      position_y: node.position.y,
      config: (node.data.config ?? {}) as WorkflowNodeConfig,
    })),
    edges: edges.map((edge) => {
      const sourceHandle = edge.sourceHandle ?? undefined
      const targetHandle = edge.targetHandle ?? undefined
      return {
        source_node_id: edge.source,
        target_node_id: edge.target,
        ...(sourceHandle ? { source_handle: sourceHandle } : {}),
        ...(targetHandle ? { target_handle: targetHandle } : {}),
        label: typeof edge.label === 'string' ? edge.label : undefined,
        condition: edge.data?.condition as WorkflowEdgeCondition | undefined,
      }
    }),
  }
}
