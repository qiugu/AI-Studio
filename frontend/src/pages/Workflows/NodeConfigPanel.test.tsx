// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { Node } from 'reactflow'

import NodeConfigPanel from './NodeConfigPanel'

const {
  listModelsMock,
  listKnowledgeBasesMock,
  listPromptsMock,
  listPluginsMock,
  listEndpointsMock,
} = vi.hoisted(() => ({
  listModelsMock: vi.fn(),
  listKnowledgeBasesMock: vi.fn(),
  listPromptsMock: vi.fn(),
  listPluginsMock: vi.fn(),
  listEndpointsMock: vi.fn(),
}))

vi.mock('@/api/ai-model', () => ({ listModels: listModelsMock }))
vi.mock('@/api/knowledge', () => ({ listKnowledgeBases: listKnowledgeBasesMock }))
vi.mock('@/api/prompt', () => ({ listPrompts: listPromptsMock }))
vi.mock('@/api/plugin', () => ({
  listPlugins: listPluginsMock,
  listEndpoints: listEndpointsMock,
}))

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
  listPluginsMock.mockResolvedValue({ data: { items: [] } })
  listEndpointsMock.mockResolvedValue({ data: [] })
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

  it('结束节点可以配置要展示的输出变量', async () => {
    const onSave = vi.fn()
    const endNode = {
      id: 'end-1',
      type: 'end',
      position: { x: 0, y: 0 },
      data: {
        name: '结束',
        config: { output_variables: [] },
      },
    } as Node

    render(<NodeConfigPanel visible node={endNode} onClose={vi.fn()} onSave={onSave} />)

    expect(await screen.findByText('输出变量')).toBeDefined()
    fireEvent.click(screen.getByRole('button', { name: '添加输出变量' }))

    fireEvent.change(screen.getByRole('textbox', { name: '变量名' }), {
      target: { value: 'answer' },
    })
    fireEvent.change(screen.getByRole('textbox', { name: '来源变量' }), {
      target: { value: 'output' },
    })
    fireEvent.click(screen.getByRole('button', { name: /保\s*存/ }))

    await waitFor(() => expect(onSave).toHaveBeenCalled())
    expect(onSave).toHaveBeenCalledWith('end-1', {
      name: '结束',
      config: { output_variables: [{ name: 'answer', source: 'output' }] },
    })
  })

  it('LLM 节点可以配置多轮工具调用能力和最大调用轮数', async () => {
    const onSave = vi.fn()
    const toolEnabledLlmNode = {
      id: 'llm-tool-1',
      type: 'llm',
      position: { x: 0, y: 0 },
      data: {
        name: '智能查询',
        config: {
          model_id: 'model-uuid-1',
          prompt_template: '请回答用户问题',
          tool_bindings: [
            {
              name: '天气查询',
              description: '查询天气',
              tool_type: 'plugin',
              config: { plugin_id: 'plugin-1', endpoint_id: 'endpoint-1' },
            },
          ],
          max_tool_rounds: 3,
        },
      },
    } as Node

    render(
      <NodeConfigPanel
        visible
        node={toolEnabledLlmNode}
        onClose={vi.fn()}
        onSave={onSave}
      />,
    )

    expect(await screen.findByText('工具调用能力')).toBeDefined()
    expect((screen.getByRole('textbox', { name: '能力名称' }) as HTMLInputElement).value).toBe(
      '天气查询',
    )
    expect(screen.getByRole('spinbutton', { name: '最大工具调用轮数' })).toBeDefined()

    fireEvent.click(screen.getByRole('button', { name: /保\s*存/ }))
    await waitFor(() => expect(onSave).toHaveBeenCalled())
    expect(onSave).toHaveBeenCalledWith('llm-tool-1', {
      name: '智能查询',
      config: expect.objectContaining({
        max_tool_rounds: 3,
        tool_bindings: [
          expect.objectContaining({
            name: '天气查询',
            tool_type: 'plugin',
            config: { plugin_id: 'plugin-1', endpoint_id: 'endpoint-1' },
          }),
        ],
      }),
    })
  })
})

describe('工具、循环和变量节点配置', () => {
  it('插件工具可以从插件目录选择插件和具体端点，并保存引用', async () => {
    const onSave = vi.fn()
    listPluginsMock.mockResolvedValue({
      data: {
        items: [
          {
            id: 'plugin-1',
            tenant_id: 'tenant-1',
            name: '天气插件',
            source_type: 'http',
            version: '1.0.0',
            status: 'active',
            is_public: false,
            endpoints: [],
          },
        ],
      },
    })
    listEndpointsMock.mockResolvedValue({
      data: [
        {
          id: 'endpoint-1',
          plugin_id: 'plugin-1',
          endpoint: '/weather',
          method: 'POST',
          description: '查询天气',
        },
      ],
    })
    const pluginNode = {
      id: 'tool-plugin-1',
      type: 'tool',
      position: { x: 0, y: 0 },
      data: {
        name: '天气查询',
        config: {
          tool_type: 'plugin',
          tool_name: '天气查询',
          output_variable: 'weather',
          tool_config: { params: {} },
        },
      },
    } as Node

    render(<NodeConfigPanel visible node={pluginNode} onClose={vi.fn()} onSave={onSave} />)

    await waitFor(() => {
      expect(listPluginsMock).toHaveBeenCalledWith({
        page: 1,
        page_size: 200,
        include_public: true,
        source_type: 'http',
        status: 'active',
      })
    })
    const pluginSelect = await screen.findByRole('combobox', { name: '插件' })
    fireEvent.mouseDown(pluginSelect)
    fireEvent.click(await screen.findByText('天气插件'))

    await waitFor(() => expect(listEndpointsMock).toHaveBeenCalledWith('plugin-1'))
    const endpointSelect = await screen.findByRole('combobox', { name: '插件端点' })
    fireEvent.mouseDown(endpointSelect)
    fireEvent.click(await screen.findByText(/POST \/weather/))
    fireEvent.click(screen.getByRole('button', { name: /保\s*存/ }))

    await waitFor(() => expect(onSave).toHaveBeenCalled())
    expect(onSave).toHaveBeenCalledWith('tool-plugin-1', {
      name: '天气查询',
      config: expect.objectContaining({
        tool_type: 'plugin',
        tool_config: expect.objectContaining({
          plugin_id: 'plugin-1',
          endpoint_id: 'endpoint-1',
        }),
      }),
    })
  })

  it('工具节点提供完整的工具调用配置，而不是显示暂无配置项', async () => {
    const onSave = vi.fn()
    const toolNode = {
      id: 'tool-1',
      type: 'tool',
      position: { x: 0, y: 0 },
      data: {
        name: '调用工具',
        config: {
          tool_type: 'api',
          tool_name: '天气查询',
          input_variables: ['city'],
          output_variable: 'weather',
          tool_config: { url: 'https://example.com/weather', method: 'GET' },
        },
      },
    } as Node

    render(<NodeConfigPanel visible node={toolNode} onClose={vi.fn()} onSave={onSave} />)

    expect(await screen.findByRole('combobox', { name: '工具类型' })).toBeDefined()
    expect(screen.getByRole('textbox', { name: '工具名称' })).toBeDefined()
    expect(screen.getByRole('combobox', { name: '输入变量' })).toBeDefined()
    expect(screen.getByRole('textbox', { name: '输出变量名' })).toBeDefined()
    expect(screen.getByRole('textbox', { name: '工具配置 JSON' })).toBeDefined()
    expect(screen.queryByText('此节点类型暂无配置项')).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: /保\s*存/ }))
    await waitFor(() => expect(onSave).toHaveBeenCalled())
    expect(onSave).toHaveBeenCalledWith('tool-1', {
      name: '调用工具',
      config: expect.objectContaining({
        tool_type: 'api',
        tool_name: '天气查询',
        input_variables: ['city'],
        output_variable: 'weather',
        tool_config: { url: 'https://example.com/weather', method: 'GET' },
      }),
    })
  })

  it('循环节点支持 for/while 的必要配置', async () => {
    const loopNode = {
      id: 'loop-1',
      type: 'loop',
      position: { x: 0, y: 0 },
      data: {
        name: '遍历列表',
        config: { loop_type: 'for', loop_variable: 'item', loop_source: 'items', max_iterations: 20 },
      },
    } as Node

    render(<NodeConfigPanel visible node={loopNode} onClose={vi.fn()} onSave={vi.fn()} />)

    expect(await screen.findByRole('combobox', { name: '循环类型' })).toBeDefined()
    expect(screen.getByRole('textbox', { name: '当前项名称' })).toBeDefined()
    expect(screen.getByRole('textbox', { name: '遍历集合' })).toBeDefined()
    expect(screen.getByRole('spinbutton', { name: '安全上限' })).toBeDefined()
    expect(screen.getByRole('alert').textContent).toContain('循环体')
    expect(screen.getByRole('alert').textContent).toContain('完成后')
  })

  it('变量节点根据变量类型显示上下文来源或表达式字段', async () => {
    const variableNode = {
      id: 'variable-2',
      type: 'variable',
      position: { x: 0, y: 0 },
      data: {
        name: '准备变量',
        config: {
          variables: [
            { name: 'city', type: 'context', source: 'input.city' },
            { name: 'is_big', type: 'expression', expression: '{{count}} > 10' },
          ],
        },
      },
    } as Node

    render(<NodeConfigPanel visible node={variableNode} onClose={vi.fn()} onSave={vi.fn()} />)

    expect(await screen.findByPlaceholderText('上下文变量名')).toBeDefined()
    expect(screen.getByPlaceholderText('表达式，例如 {{count}} > 10')).toBeDefined()
  })
})
