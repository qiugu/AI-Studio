// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import AgentInfo from './AgentInfo'
import type { Agent } from '@/types/agent'

function agent(partial: Partial<Agent> = {}): Agent {
  return {
    id: 'agent-1',
    tenant_id: 'tenant-1',
    name: '知识运营助手',
    description: '帮助团队检索知识并执行标准化任务。',
    avatar: null,
    system_prompt: null,
    model_id: 1,
    temperature: 0.2,
    max_tokens: 2048,
    status: 'published',
    created_by: 1,
    created_at: '2026-10-12T00:00:00Z',
    updated_at: '2026-10-12T00:00:00Z',
    deleted_at: null,
    tools: [],
    ...partial,
  }
}

describe('AgentInfo 工作上下文', () => {
  it('展示 Agent 状态、授权能力和能力类型，而不是只显示装饰性描述', () => {
    render(
      <AgentInfo
        agent={agent({
          tools: [
            {
              id: 'tool-1',
              agent_id: 'agent-1',
              tenant_id: 'tenant-1',
              tool_type: 'knowledge',
              config: {},
              name: '企业知识库',
              description: null,
              is_enabled: true,
              created_at: '2026-10-12T00:00:00Z',
              updated_at: '2026-10-12T00:00:00Z',
            },
            {
              id: 'tool-2',
              agent_id: 'agent-1',
              tenant_id: 'tenant-1',
              tool_type: 'plugin',
              config: {},
              name: '工单系统',
              description: null,
              is_enabled: true,
              created_at: '2026-10-12T00:00:00Z',
              updated_at: '2026-10-12T00:00:00Z',
            },
          ],
        })}
      />,
    )

    expect(screen.getByText('已发布')).toBeTruthy()
    expect(screen.getByText(/项已授权能力/)).toBeTruthy()
    expect(screen.getByText('知识库')).toBeTruthy()
    expect(screen.getByText('插件')).toBeTruthy()
  })
})
