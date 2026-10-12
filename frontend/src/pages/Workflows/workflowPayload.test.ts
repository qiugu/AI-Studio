import { describe, expect, it, vi } from 'vitest'
import type { Edge, Node } from 'reactflow'

import { buildWorkflowGraphPayload } from './workflowPayload'

describe('buildWorkflowGraphPayload', () => {
  it('preserves UUID and temporary references while assigning every node a client reference', () => {
    const persistedId = '57632460-99bf-4b55-bb62-3d3ec13dcdeb'
    const nodes: Node[] = [
      {
        id: persistedId,
        type: 'start',
        position: { x: 10, y: 20 },
        data: { name: '开始', config: {}, onEdit: vi.fn() },
      },
      {
        id: 'temp-123',
        type: 'end',
        position: { x: 30, y: 40 },
        data: { name: '结束', config: { output_variables: [] }, onDelete: vi.fn() },
      },
    ]
    const edges: Edge[] = [
      {
        id: 'edge-1',
        source: persistedId,
        target: 'temp-123',
        label: 'next',
        data: { condition: { expression: 'true', label: '通过' } },
      },
    ]

    expect(buildWorkflowGraphPayload(nodes, edges)).toEqual({
      nodes: [
        {
          temp_id: persistedId,
          node_type: 'start',
          name: '开始',
          position_x: 10,
          position_y: 20,
          config: {},
        },
        {
          temp_id: 'temp-123',
          node_type: 'end',
          name: '结束',
          position_x: 30,
          position_y: 40,
          config: { output_variables: [] },
        },
      ],
      edges: [
        {
          source_node_id: persistedId,
          target_node_id: 'temp-123',
          label: 'next',
          condition: { expression: 'true', label: '通过' },
        },
      ],
    })
  })
})
