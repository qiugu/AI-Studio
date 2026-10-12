// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { Node } from 'reactflow'

import NodeConfigPanel from './NodeConfigPanel'

const { listModelsMock, listKnowledgeBasesMock, listPromptsMock } = vi.hoisted(() => ({
  listModelsMock: vi.fn(),
  listKnowledgeBasesMock: vi.fn(),
  listPromptsMock: vi.fn(),
}))

vi.mock('@/api/ai-model', () => ({ listModels: listModelsMock }))
vi.mock('@/api/knowledge', () => ({ listKnowledgeBases: listKnowledgeBasesMock }))
vi.mock('@/api/prompt', () => ({ listPrompts: listPromptsMock }))

vi.mock('antd', async (importOriginal) => {
  const actual = await importOriginal<typeof import('antd')>()
  return {
    ...actual,
    message: { success: vi.fn(), error: vi.fn() },
  }
})

const llmNode = {
  id: 'node-1',
  type: 'llm',
  position: { x: 0, y: 0 },
  data: {
    name: '生成回答',
    config: { model_id: 'model-uuid-1' },
  },
} as Node

beforeEach(() => {
  vi.clearAllMocks()
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }),
  })
  window.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver

  listModelsMock.mockResolvedValue({
    data: {
      items: [
        {
          id: 'model-uuid-1',
          tenant_id: 'tenant-1',
          provider_id: 'provider-1',
          name: 'gpt-4o',
          display_name: 'GPT-4o',
          model_type: 'chat',
          config: null,
          unit_price_input: null,
          unit_price_output: null,
          max_context_tokens: 128000,
          max_output_tokens: 4096,
          status: true,
          created_at: null,
          updated_at: null,
        },
      ],
    },
  })
  listKnowledgeBasesMock.mockResolvedValue({
    data: {
      items: [
        {
          id: '390f50ec-633f-456e-94be-840910b11241',
          name: '产品知识库',
        },
      ],
    },
  })
  listPromptsMock.mockResolvedValue({
    data: {
      items: [
        {
          id: 'prompt-uuid-1',
          tenant_id: 'tenant-1',
          name: '客服回答模板',
          description: null,
          category: '客服',
          tags: null,
          status: 'published',
          created_by: null,
          created_at: null,
          updated_at: null,
          current_version: {
            id: 'prompt-version-uuid-1',
            prompt_id: 'prompt-uuid-1',
            version_number: 3,
            content: '请根据 {{knowledge_result}} 回答 {{question}}',
            variables: ['knowledge_result', 'question'],
            is_current: true,
            created_by: null,
            created_at: null,
          },
        },
      ],
    },
  })
})

afterEach(cleanup)

describe('LLM 节点模型配置', () => {
  it('从已配置的 Chat 模型中选择，而不是手工输入数字 ID', async () => {
    render(
      <NodeConfigPanel
        visible
        node={llmNode}
        onClose={vi.fn()}
        onSave={vi.fn()}
      />,
    )

    await waitFor(() => {
      expect(listModelsMock).toHaveBeenCalledWith({
        page: 1,
        page_size: 200,
        model_type: 'chat',
      })
    })

    expect(await screen.findByRole('combobox', { name: '模型' })).toBeDefined()
    expect(await screen.findByText('GPT-4o')).toBeDefined()
  })

  it('已有节点引用停用模型时显示名称和停用状态，避免退化成裸 UUID', async () => {
    listModelsMock.mockResolvedValue({
      data: {
        items: [
          {
            id: 'model-uuid-1',
            tenant_id: 'tenant-1',
            provider_id: 'provider-1',
            name: 'gpt-4o',
            display_name: 'GPT-4o',
            model_type: 'chat',
            config: null,
            unit_price_input: null,
            unit_price_output: null,
            max_context_tokens: 128000,
            max_output_tokens: 4096,
            status: false,
            created_at: null,
            updated_at: null,
          },
        ],
      },
    })

    render(
      <NodeConfigPanel
        visible
        node={llmNode}
        onClose={vi.fn()}
        onSave={vi.fn()}
      />,
    )

    expect(await screen.findByText('GPT-4o（已停用）')).toBeDefined()
    expect(screen.queryByText('model-uuid-1')).toBeNull()
  })

  it('可选择已保存 Prompt，并把当前版本内容与版本标识写入节点配置', async () => {
    const onSave = vi.fn()
    render(
      <NodeConfigPanel visible node={llmNode} onClose={vi.fn()} onSave={onSave} />,
    )

    await waitFor(() => {
      expect(listPromptsMock).toHaveBeenCalledWith({ page: 1, page_size: 200 })
    })

    const promptSelect = await screen.findByRole('combobox', { name: '已保存 Prompt' })
    fireEvent.mouseDown(promptSelect)
    fireEvent.click(await screen.findByText('客服回答模板 · v3'))

    await waitFor(() => {
      expect(
        (screen.getByRole('textbox', { name: 'Prompt模板' }) as HTMLTextAreaElement).value,
      ).toBe('请根据 {{knowledge_result}} 回答 {{question}}')
    })

    fireEvent.click(screen.getByRole('button', { name: /保\s*存/ }))
    await waitFor(() => expect(onSave).toHaveBeenCalled())
    expect(onSave).toHaveBeenCalledWith('node-1', {
      name: '生成回答',
      config: expect.objectContaining({
        prompt_id: 'prompt-uuid-1',
        prompt_version_id: 'prompt-version-uuid-1',
        prompt_template: '请根据 {{knowledge_result}} 回答 {{question}}',
      }),
    })
  })

  it('切换节点时清理旧节点字段，且节点名称不写入 config', async () => {
    const onSave = vi.fn()
    const codeNode = {
      id: 'code-1',
      type: 'code',
      position: { x: 0, y: 0 },
      data: {
        name: '代码',
        config: { code: 'return 1', output_variable: 'result' },
      },
    } as Node
    const variableNode = {
      id: 'variable-1',
      type: 'variable',
      position: { x: 0, y: 0 },
      data: { name: '变量', config: { variables: [] } },
    } as Node

    const view = render(
      <NodeConfigPanel visible node={codeNode} onClose={vi.fn()} onSave={onSave} />,
    )
    view.rerender(
      <NodeConfigPanel visible node={variableNode} onClose={vi.fn()} onSave={onSave} />,
    )

    await waitFor(() => {
      const input = screen.getByRole('textbox', { name: '节点名称' }) as HTMLInputElement
      expect(input.value).toBe('变量')
    })
    fireEvent.click(screen.getByRole('button', { name: /保\s*存/ }))

    await waitFor(() => expect(onSave).toHaveBeenCalled())
    expect(onSave).toHaveBeenCalledWith('variable-1', {
      name: '变量',
      config: { variables: [] },
    })
  })

  it('知识库节点从已配置知识库中选择 UUID', async () => {
    const knowledgeNode = {
      id: 'knowledge-1',
      type: 'knowledge',
      position: { x: 0, y: 0 },
      data: {
        name: '知识检索',
        config: {
          knowledge_base_id: '390f50ec-633f-456e-94be-840910b11241',
          query_template: '{{input}}',
        },
      },
    } as Node

    render(
      <NodeConfigPanel visible node={knowledgeNode} onClose={vi.fn()} onSave={vi.fn()} />,
    )

    await waitFor(() => expect(listKnowledgeBasesMock).toHaveBeenCalledWith(1, 100))
    expect(await screen.findByRole('combobox', { name: '知识库' })).toBeDefined()
    expect(await screen.findByText('产品知识库')).toBeDefined()
  })
})
