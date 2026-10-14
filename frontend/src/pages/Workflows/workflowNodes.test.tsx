// @vitest-environment jsdom
import { render, screen } from '@testing-library/react'
import { ReactFlowProvider } from 'reactflow'
import type { NodeProps } from 'reactflow'
import { describe, expect, it } from 'vitest'

import CustomNode from './workflowNodes'

describe('workflow node visual shell', () => {
  it('uses the compact node shell and exposes saved Prompt context', () => {
    const props = {
      id: 'node-1',
      data: {
        name: '回答生成',
        config: {
          model_id: 'model-1',
          prompt_id: 'prompt-1',
        },
      },
      selected: false,
      nodeType: 'llm',
    } as unknown as NodeProps & { nodeType: 'llm' }

    const { container } = render(
      <ReactFlowProvider>
        <CustomNode {...props} />
      </ReactFlowProvider>,
    )
    const node = container.querySelector('.workflow-node')

    expect(node?.className).toContain('workflow-node--compact')
    expect(node?.getAttribute('data-type')).toBe('llm')
    expect(screen.getByText('Prompt · 已关联')).toBeDefined()
  })
})
