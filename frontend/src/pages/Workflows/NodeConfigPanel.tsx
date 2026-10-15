import React from 'react'
import { Alert, Drawer, Form, Input, Select, InputNumber, Button, Space, message } from 'antd'
import type { Node } from 'reactflow'
import { listModels } from '@/api/ai-model'
import { listKnowledgeBases } from '@/api/knowledge'
import { listPrompts } from '@/api/prompt'
import { listEndpoints, listPlugins } from '@/api/plugin'
import type { AIModel } from '@/types/ai-model'
import type { KnowledgeBase } from '@/types/knowledge'
import type { Prompt } from '@/types/prompt'
import type { Plugin, PluginEndpoint } from '@/types/plugin'
import type { NodeType, WorkflowNodeConfig, WorkflowToolBinding } from '../../types/workflow'

interface NodeConfigPanelProps {
  visible: boolean
  node: Node | null
  onClose: () => void
  onSave: (nodeId: string, data: { name: string; config: WorkflowNodeConfig }) => void
}

const NodeConfigPanel: React.FC<NodeConfigPanelProps> = ({
  visible,
  node,
  onClose,
  onSave,
}) => {
  const [form] = Form.useForm()
  const [models, setModels] = React.useState<AIModel[]>([])
  const [modelsLoaded, setModelsLoaded] = React.useState(false)
  const [prompts, setPrompts] = React.useState<Prompt[]>([])
  const [promptsLoaded, setPromptsLoaded] = React.useState(false)
  const [knowledgeBases, setKnowledgeBases] = React.useState<KnowledgeBase[]>([])
  const [knowledgeBasesLoaded, setKnowledgeBasesLoaded] = React.useState(false)
  const [plugins, setPlugins] = React.useState<Plugin[]>([])
  const [pluginsLoaded, setPluginsLoaded] = React.useState(false)
  const [pluginEndpoints, setPluginEndpoints] = React.useState<PluginEndpoint[]>([])
  const [endpointPluginId, setEndpointPluginId] = React.useState<string | null>(null)
  const [llmPluginEndpoints, setLlmPluginEndpoints] = React.useState<Record<string, PluginEndpoint[]>>({})
  const modelsLoading = visible && node?.type === 'llm' && !modelsLoaded
  const promptsLoading = visible && node?.type === 'llm' && !promptsLoaded
  const knowledgeBasesLoading = visible && node?.type === 'knowledge' && !knowledgeBasesLoaded
  const selectedModelId = Form.useWatch('model_id', form)
  const selectedModel = models.find((model) => model.id === selectedModelId)
  const selectedPromptId = Form.useWatch('prompt_id', form)
  const selectedPrompt = prompts.find((prompt) => prompt.id === selectedPromptId)
  const selectedToolType = Form.useWatch('tool_type', form)
  const selectedPluginId = Form.useWatch('plugin_id', form)
  const selectedLoopType = Form.useWatch('loop_type', form)
  const watchedToolBindings = (Form.useWatch('tool_bindings', form) as WorkflowToolBinding[] | undefined) ?? []
  const bindingPluginKey = watchedToolBindings
    .map((binding) => String(binding?.config?.plugin_id ?? ''))
    .filter(Boolean)
    .sort()
    .join('|')

  React.useEffect(() => {
    if (node) {
      form.resetFields()
      const savedToolConfig = node.data.config?.tool_config ?? {}
      form.setFieldsValue({
        name: node.data.name,
        ...node.data.config,
        plugin_id: savedToolConfig.plugin_id,
        endpoint_id: savedToolConfig.endpoint_id,
        tool_bindings: node.data.config?.tool_bindings ?? [],
        max_tool_rounds: node.data.config?.max_tool_rounds ?? 5,
        tool_config_json: node.data.config?.tool_config
          ? JSON.stringify(node.data.config.tool_config, null, 2)
          : '{}',
      })
    }
  }, [node, form])

  React.useEffect(() => {
    if (!visible || node?.type !== 'llm' || modelsLoaded) return

    let active = true
    listModels({ page: 1, page_size: 200, model_type: 'chat' })
      .then((response) => {
        if (active) {
          setModels(response.data?.items ?? [])
        }
      })
      .catch(() => {
        if (active) {
          setModels([])
          message.error('加载可用模型失败')
        }
      })
      .finally(() => {
        if (active) setModelsLoaded(true)
      })

    return () => {
      active = false
    }
  }, [visible, node?.type, modelsLoaded])

  React.useEffect(() => {
    if (!visible || node?.type !== 'llm' || promptsLoaded) return

    let active = true
    listPrompts({ page: 1, page_size: 200 })
      .then((response) => {
        if (active) {
          setPrompts(response.data?.items ?? [])
        }
      })
      .catch(() => {
        if (active) {
          setPrompts([])
          message.error('加载已保存 Prompt 失败')
        }
      })
      .finally(() => {
        if (active) setPromptsLoaded(true)
      })

    return () => {
      active = false
    }
  }, [visible, node?.type, promptsLoaded])

  React.useEffect(() => {
    if (!visible || node?.type !== 'knowledge' || knowledgeBasesLoaded) return

    let active = true
    listKnowledgeBases(1, 100)
      .then((response) => {
        if (active) {
          setKnowledgeBases(response.data?.items ?? [])
        }
      })
      .catch(() => {
        if (active) {
          setKnowledgeBases([])
          message.error('加载知识库失败')
        }
      })
      .finally(() => {
        if (active) setKnowledgeBasesLoaded(true)
      })

    return () => {
      active = false
    }
  }, [visible, node?.type, knowledgeBasesLoaded])

  React.useEffect(() => {
    const shouldLoadPlugins =
      node?.type === 'llm' || (node?.type === 'tool' && selectedToolType === 'plugin')
    if (!visible || !shouldLoadPlugins || pluginsLoaded) return

    let active = true
    listPlugins({
      page: 1,
      page_size: 200,
      include_public: true,
      source_type: 'http',
      status: 'active',
    })
      .then((response) => {
        if (active) setPlugins(response.data?.items ?? [])
      })
      .catch(() => {
        if (active) {
          setPlugins([])
          message.error('加载可用插件失败')
        }
      })
      .finally(() => {
        if (active) setPluginsLoaded(true)
      })

    return () => {
      active = false
    }
  }, [visible, node?.type, selectedToolType, pluginsLoaded])

  React.useEffect(() => {
    if (!visible || node?.type !== 'tool' || selectedToolType !== 'plugin' || !selectedPluginId) return

    let active = true
    listEndpoints(selectedPluginId)
      .then((response) => {
        if (active) {
          setPluginEndpoints(response.data ?? [])
          setEndpointPluginId(selectedPluginId)
        }
      })
      .catch(() => {
        if (active) {
          setPluginEndpoints([])
          setEndpointPluginId(null)
          message.error('加载插件端点失败')
        }
      })

    return () => {
      active = false
    }
  }, [visible, node?.type, selectedToolType, selectedPluginId])

  React.useEffect(() => {
    if (!visible || node?.type !== 'llm' || !bindingPluginKey) {
      return
    }

    let active = true
    const pluginIds = Array.from(new Set(bindingPluginKey.split('|')))
    Promise.all(
      pluginIds.map(async (pluginId) => {
        const response = await listEndpoints(pluginId)
        return [pluginId, response.data ?? []] as const
      }),
    )
      .then((entries) => {
        if (active) setLlmPluginEndpoints(Object.fromEntries(entries))
      })
      .catch(() => {
        if (active) {
          setLlmPluginEndpoints({})
          message.error('加载工具能力失败')
        }
      })

    return () => {
      active = false
    }
  }, [visible, node?.type, bindingPluginKey])

  const handleSave = () => {
    form.validateFields().then((values) => {
      const { name, tool_config_json, plugin_id, endpoint_id, ...config } = values
      if (node?.type === 'tool') {
        try {
          const parsedToolConfig = tool_config_json?.trim() ? JSON.parse(tool_config_json) : {}
          if (!parsedToolConfig || Array.isArray(parsedToolConfig) || typeof parsedToolConfig !== 'object') {
            message.error('工具配置必须是 JSON 对象')
            return
          }
          config.tool_config =
            config.tool_type === 'plugin'
              ? { ...parsedToolConfig, plugin_id, endpoint_id }
              : parsedToolConfig
        } catch {
          message.error('工具配置必须是合法的 JSON')
          return
        }
      }
      onSave(node!.id, {
        name,
        config,
      })
      message.success('节点配置已保存')
      onClose()
    })
  }

  const renderOutputVariables = () => (
    <Form.List name="output_variables">
      {(fields, { add, remove }) => (
        <>
          <div style={{ marginBottom: 8 }}>输出变量</div>
          {fields.map(({ key, name, ...restField }) => (
            <Space key={key} style={{ display: 'flex', marginBottom: 8 }} align="baseline">
              <Form.Item
                {...restField}
                name={[name, 'name']}
                rules={[{ required: true, message: '请输入变量名' }]}
              >
                <Input placeholder="变量名" aria-label="变量名" />
              </Form.Item>
              <Form.Item
                {...restField}
                name={[name, 'source']}
                rules={[{ required: true, message: '请输入来源变量' }]}
              >
                <Input placeholder="来源变量" aria-label="来源变量" />
              </Form.Item>
              <Button onClick={() => remove(name)}>删除</Button>
            </Space>
          ))}
          <Button type="dashed" onClick={() => add()}>
            添加输出变量
          </Button>
        </>
      )}
    </Form.List>
  )

  const renderConfigFields = (nodeType: NodeType) => {
    switch (nodeType) {
      case 'start':
      case 'end':
        return renderOutputVariables()

      case 'llm':
        return (
          <>
            <Form.Item
              label="模型"
              name="model_id"
              rules={[{ required: true, message: '请选择模型' }]}
              extra={
                selectedModel
                  ? selectedModel.status
                    ? `${selectedModel.name}${selectedModel.max_output_tokens ? ` · 最大输出 ${selectedModel.max_output_tokens} Token` : ''}`
                    : '当前模型已停用，请重新选择可用模型'
                  : '仅显示模型管理中已启用的 Chat 模型'
              }
            >
              <Select
                showSearch
                optionFilterProp="label"
                loading={modelsLoading}
                placeholder="选择已配置的 Chat 模型"
                notFoundContent={modelsLoading ? '正在加载模型…' : '暂无可用 Chat 模型'}
                options={models.map((model) => ({
                  value: model.id,
                  label: `${model.display_name}${model.status ? '' : '（已停用）'}`,
                  disabled: !model.status,
                }))}
              />
            </Form.Item>
            <Form.Item
              label="已保存 Prompt"
              name="prompt_id"
              extra={
                selectedPrompt?.current_version
                  ? `已载入 v${selectedPrompt.current_version.version_number}；可在下方做节点级微调，后续版本升级不会自动覆盖本节点`
                  : '可选；从 Prompt 管理中复用当前版本，归档或无内容的 Prompt 不可选择'
              }
            >
              <Select
                allowClear
                showSearch
                optionFilterProp="label"
                loading={promptsLoading}
                placeholder="选择 Prompt 管理中已保存的模板"
                notFoundContent={promptsLoading ? '正在加载 Prompt…' : '暂无可用 Prompt'}
                options={prompts.map((prompt) => ({
                  value: prompt.id,
                  label: `${prompt.name}${prompt.current_version ? ` · v${prompt.current_version.version_number}` : '（无当前版本）'}${prompt.status === 'archived' ? '（已归档）' : ''}`,
                  disabled: prompt.status === 'archived' || !prompt.current_version,
                }))}
                onChange={(promptId) => {
                  if (!promptId) {
                    form.setFieldValue('prompt_version_id', undefined)
                    return
                  }
                  const prompt = prompts.find((item) => item.id === promptId)
                  if (!prompt?.current_version) return
                  form.setFieldsValue({
                    prompt_version_id: prompt.current_version.id,
                    prompt_template: prompt.current_version.content,
                  })
                }}
              />
            </Form.Item>
            <Form.Item name="prompt_version_id" hidden>
              <Input />
            </Form.Item>
            <Form.Item label="Prompt模板" name="prompt_template" rules={[{ required: true }]}>
              <Input.TextArea rows={6} placeholder="使用 {{variable}} 插入变量" />
            </Form.Item>
            <div className="workflow-tool-binding-section">
              <div className="workflow-tool-binding-title">工具调用能力</div>
              <div className="workflow-tool-binding-help">
                可选。模型会在需要时自主调用已绑定的插件，并在拿到结果后继续思考。
              </div>
              <Form.List name="tool_bindings">
                {(fields, { add, remove }) => (
                  <>
                    {fields.map(({ key, name, ...restField }) => {
                      const binding = form.getFieldValue(['tool_bindings', name]) as
                        | WorkflowToolBinding
                        | undefined
                      const pluginId = String(binding?.config?.plugin_id ?? '')
                      const endpoints = llmPluginEndpoints[pluginId] ?? []

                      return (
                        <div className="workflow-tool-binding-card" key={key}>
                          <Form.Item
                            {...restField}
                            label="能力名称"
                            name={[name, 'name']}
                            rules={[{ required: true, message: '请输入能力名称' }]}
                          >
                            <Input placeholder="例如：天气查询" aria-label="能力名称" />
                          </Form.Item>
                          <Form.Item
                            {...restField}
                            label="能力说明"
                            name={[name, 'description']}
                          >
                            <Input placeholder="告诉模型什么时候使用这项能力" />
                          </Form.Item>
                          <Form.Item
                            {...restField}
                            name={[name, 'tool_type']}
                            initialValue="plugin"
                            hidden
                          >
                            <Input />
                          </Form.Item>
                          <Form.Item
                            {...restField}
                            label="插件"
                            name={[name, 'config', 'plugin_id']}
                            rules={[{ required: true, message: '请选择插件' }]}
                          >
                            <Select
                              showSearch
                              optionFilterProp="label"
                              loading={!pluginsLoaded}
                              placeholder="选择可用插件"
                              options={plugins.map((plugin) => ({
                                value: plugin.id,
                                label: `${plugin.name}${plugin.is_public ? '（平台公共）' : ''}`,
                              }))}
                              onChange={() =>
                                form.setFieldValue(
                                  ['tool_bindings', name, 'config', 'endpoint_id'],
                                  undefined,
                                )
                              }
                            />
                          </Form.Item>
                          <Form.Item
                            {...restField}
                            label="可调用能力"
                            name={[name, 'config', 'endpoint_id']}
                            rules={[{ required: true, message: '请选择可调用能力' }]}
                          >
                            <Select
                              showSearch
                              optionFilterProp="label"
                              loading={Boolean(pluginId) && !llmPluginEndpoints[pluginId]}
                              placeholder={pluginId ? '选择插件能力' : '请先选择插件'}
                              notFoundContent={pluginId ? '暂无可用能力' : '请先选择插件'}
                              options={endpoints.map((endpoint) => ({
                                value: endpoint.id,
                                label: `${endpoint.method.toUpperCase()} ${endpoint.endpoint}${endpoint.description ? ` · ${endpoint.description}` : ''}`,
                              }))}
                            />
                          </Form.Item>
                          <Button type="link" danger onClick={() => remove(name)}>
                            移除这项能力
                          </Button>
                        </div>
                      )
                    })}
                    <Button
                      type="dashed"
                      onClick={() =>
                        add({
                          name: '',
                          description: '',
                          tool_type: 'plugin',
                          config: {},
                          is_enabled: true,
                        })
                      }
                    >
                      添加插件能力
                    </Button>
                  </>
                )}
              </Form.List>
            </div>
            <Form.Item
              label="最大工具调用轮数"
              name="max_tool_rounds"
              extra="模型最多连续调用工具多少轮，用于防止意外循环；默认 5 轮"
              rules={[{ required: true, message: '请输入最大工具调用轮数' }]}
            >
              <InputNumber
                min={1}
                max={20}
                style={{ width: '100%' }}
                aria-label="最大工具调用轮数"
              />
            </Form.Item>
            <Form.Item
              label="Temperature"
              name="temperature"
              extra="本次节点调用参数，不修改模型配置"
            >
              <InputNumber min={0} max={2} step={0.1} />
            </Form.Item>
            <Form.Item
              label="本次最大输出 Token"
              name="max_tokens"
              extra={
                selectedModel?.max_output_tokens
                  ? `不得超过模型能力上限 ${selectedModel.max_output_tokens}`
                  : '留空时使用工作流默认值 2000'
              }
              rules={[
                {
                  validator: (_, value) => {
                    if (
                      value == null ||
                      !selectedModel?.max_output_tokens ||
                      value <= selectedModel.max_output_tokens
                    ) {
                      return Promise.resolve()
                    }
                    return Promise.reject(
                      new Error(`不能超过模型能力上限 ${selectedModel.max_output_tokens}`),
                    )
                  },
                },
              ]}
            >
              <InputNumber
                min={1}
                max={selectedModel?.max_output_tokens ?? undefined}
                style={{ width: '100%' }}
              />
            </Form.Item>
            <Form.Item label="输出变量名" name="output_variable">
              <Input placeholder="output" />
            </Form.Item>
          </>
        )

      case 'knowledge':
        return (
          <>
            <Form.Item label="知识库" name="knowledge_base_id" rules={[{ required: true }]}>
              <Select
                showSearch
                optionFilterProp="label"
                loading={knowledgeBasesLoading}
                placeholder="选择已配置的知识库"
                notFoundContent={knowledgeBasesLoading ? '正在加载知识库…' : '暂无可用知识库'}
                options={knowledgeBases.map((knowledgeBase) => ({
                  value: knowledgeBase.id,
                  label: knowledgeBase.name,
                }))}
              />
            </Form.Item>
            <Form.Item label="查询模板" name="query_template" rules={[{ required: true }]}>
              <Input.TextArea rows={4} placeholder="使用 {{variable}} 插入变量" />
            </Form.Item>
            <Form.Item label="Top K" name="top_k">
              <InputNumber min={1} max={20} />
            </Form.Item>
            <Form.Item label="输出变量名" name="output_variable">
              <Input placeholder="knowledge_result" />
            </Form.Item>
          </>
        )

      case 'condition':
        return (
          <>
            <Form.List name="conditions">
              {(fields, { add, remove }) => (
                <>
                  {fields.map(({ key, name, ...restField }) => (
                    <Space key={key} style={{ display: 'flex', marginBottom: 8 }} align="baseline">
                      <Form.Item
                        {...restField}
                        name={[name, 'expression']}
                        rules={[{ required: true, message: '请输入条件表达式' }]}
                      >
                        <Input placeholder="{{output.value > 10}}" />
                      </Form.Item>
                      <Form.Item
                        {...restField}
                        name={[name, 'label']}
                        rules={[{ required: true, message: '请输入标签' }]}
                      >
                        <Input placeholder="大于10" />
                      </Form.Item>
                      <Button onClick={() => remove(name)}>删除</Button>
                    </Space>
                  ))}
                  <Button onClick={() => add()}>添加条件</Button>
                </>
              )}
            </Form.List>
          </>
        )

      case 'code':
        return (
          <>
            <Form.Item label="Python代码" name="code" rules={[{ required: true }]}>
              <Input.TextArea
                rows={10}
                placeholder="result = input_data['value'] * 2"
              />
            </Form.Item>
            <Form.Item label="输入变量" name="input_variables">
              <Select mode="tags" placeholder="选择或输入变量名" />
            </Form.Item>
            <Form.Item label="输出变量名" name="output_variable">
              <Input placeholder="result" />
            </Form.Item>
          </>
        )

      case 'tool':
        return (
          <>
            <Form.Item
              label="工具类型"
              name="tool_type"
              rules={[{ required: true, message: '请选择工具类型' }]}
              extra="当前支持插件/API、函数和工作流调用"
            >
              <Select
                aria-label="工具类型"
                options={[
                  { value: 'plugin', label: '插件端点' },
                  { value: 'api', label: 'HTTP API' },
                  { value: 'function', label: '函数' },
                  { value: 'workflow', label: '工作流' },
                ]}
              />
            </Form.Item>
            <Form.Item
              label="工具名称"
              name="tool_name"
              rules={[{ required: true, message: '请输入工具名称' }]}
            >
              <Input placeholder="例如：天气查询" aria-label="工具名称" />
            </Form.Item>
            <Form.Item
              label="输入变量"
              name="input_variables"
              extra="填写上游节点输出的变量名，工具将按名称读取"
            >
              <Select mode="tags" placeholder="输入变量名后回车" aria-label="输入变量" />
            </Form.Item>
            <Form.Item label="输出变量名" name="output_variable">
              <Input placeholder="tool_result" aria-label="输出变量名" />
            </Form.Item>
            <Form.Item
              label="工具配置 JSON"
              name="tool_config_json"
              rules={[{ required: true, message: '请输入工具配置 JSON' }]}
              extra="插件需配置 plugin_id 与 endpoint_id；API 需配置 url 与 method；函数需配置 code"
            >
              <Input.TextArea
                rows={8}
                placeholder={'{\n  "plugin_id": "...",\n  "endpoint_id": "..."\n}'}
                aria-label="工具配置 JSON"
              />
            </Form.Item>
            {selectedToolType === 'plugin' && (
              <>
                <Form.Item
                  label="插件"
                  name="plugin_id"
                  rules={[{ required: true, message: '请选择插件' }]}
                  extra="仅显示当前租户可用的 HTTP 插件"
                >
                  <Select
                    showSearch
                    optionFilterProp="label"
                    loading={!pluginsLoaded}
                    placeholder="选择已配置的插件"
                    options={plugins.map((plugin) => ({
                      value: plugin.id,
                      label: `${plugin.name}${plugin.is_public ? '（平台公共）' : ''}`,
                    }))}
                    onChange={() => form.setFieldValue('endpoint_id', undefined)}
                  />
                </Form.Item>
                <Form.Item
                  label="插件端点"
                  name="endpoint_id"
                  rules={[{ required: true, message: '请选择插件端点' }]}
                >
                  <Select
                    showSearch
                    optionFilterProp="label"
                    loading={endpointPluginId !== selectedPluginId}
                    placeholder="选择具体端点"
                    notFoundContent={selectedPluginId ? '暂无可用端点' : '请先选择插件'}
                    options={
                      endpointPluginId === selectedPluginId
                        ? pluginEndpoints.map((endpoint) => ({
                            value: endpoint.id,
                            label: `${endpoint.method.toUpperCase()} ${endpoint.endpoint}${endpoint.description ? ` · ${endpoint.description}` : ''}`,
                          }))
                        : []
                    }
                  />
                </Form.Item>
              </>
            )}
          </>
        )

      case 'loop':
        return (
          <>
            <Alert
              className="workflow-loop-guidance"
              type="info"
              showIcon
              title="循环节点的执行方式"
              description={
                selectedLoopType === 'while'
                  ? '每次先检查循环条件，条件满足后执行循环体；条件不满足时进入完成后分支。'
                  : '每一项进入「循环体」，全部完成后继续到「完成后」。'
              }
            />
            <Form.Item
              label="循环类型"
              name="loop_type"
              rules={[{ required: true, message: '请选择循环类型' }]}
              extra="推荐使用“遍历集合”；只有需要根据运行中变量反复判断时才使用“条件循环”"
            >
              <Select
                aria-label="循环类型"
                options={[
                  { value: 'for', label: '遍历集合（推荐）' },
                  { value: 'while', label: '满足条件时重复（高级）' },
                ]}
              />
            </Form.Item>
            <Form.Item
              label="当前项名称"
              name="loop_variable"
              rules={[{ required: true, message: '请输入循环变量' }]}
              extra="循环体内使用这个变量读取当前项，例如 item"
            >
              <Input placeholder="item" aria-label="当前项名称" />
            </Form.Item>
            <Form.Item
              label="遍历集合"
              name="loop_source"
              rules={[{ required: true, message: '请输入循环数据源' }]}
              extra="填写上游节点输出的数组或列表变量名，例如 items"
            >
              <Input placeholder="items" aria-label="遍历集合" />
            </Form.Item>
            {selectedLoopType === 'while' && (
              <Form.Item
                label="循环条件"
                name="condition_template"
                rules={[{ required: true, message: '请输入循环条件' }]}
                extra="循环体需要更新条件依赖的变量，否则会一直执行到安全上限"
              >
                <Input placeholder="例如：{{count}} < 3" />
              </Form.Item>
            )}
            <Form.Item
              label="安全上限"
              name="max_iterations"
              rules={[{ required: true, message: '请输入最大迭代次数' }]}
              extra="最多执行多少项，用于防止意外的无限执行"
            >
              <InputNumber min={1} max={1000} style={{ width: '100%' }} aria-label="安全上限" />
            </Form.Item>
          </>
        )

      case 'variable':
        return (
          <>
            <Form.List name="variables">
              {(fields, { add, remove }) => (
                <>
                  {fields.map(({ key, name, ...restField }) => (
                    <Space key={key} style={{ display: 'flex', marginBottom: 8 }} align="baseline">
                      <Form.Item {...restField} name={[name, 'name']} rules={[{ required: true }]}>
                        <Input placeholder="变量名" />
                      </Form.Item>
                      <Form.Item {...restField} name={[name, 'type']} rules={[{ required: true }]}>
                        <Select style={{ width: 120 }} aria-label="变量类型">
                          <Select.Option value="static">静态值</Select.Option>
                          <Select.Option value="context">上下文引用</Select.Option>
                          <Select.Option value="expression">表达式</Select.Option>
                        </Select>
                      </Form.Item>
                      <Form.Item noStyle shouldUpdate>
                        {() => {
                          const type = form.getFieldValue(['variables', name, 'type'])
                          if (type === 'context') {
                            return (
                              <Form.Item {...restField} name={[name, 'source']}>
                                <Input placeholder="上下文变量名" />
                              </Form.Item>
                            )
                          }
                          if (type === 'expression') {
                            return (
                              <Form.Item {...restField} name={[name, 'expression']}>
                                <Input placeholder="表达式，例如 {{count}} > 10" />
                              </Form.Item>
                            )
                          }
                          return (
                            <Form.Item {...restField} name={[name, 'value']}>
                              <Input placeholder="值" />
                            </Form.Item>
                          )
                        }}
                      </Form.Item>
                      <Button onClick={() => remove(name)}>删除</Button>
                    </Space>
                  ))}
                  <Button onClick={() => add()}>添加变量</Button>
                </>
              )}
            </Form.List>
          </>
        )

      default:
        return <div>此节点类型暂无配置项</div>
    }
  }

  return (
    <Drawer
      title="节点配置"
      size={400}
      open={visible}
      onClose={onClose}
      footer={
        <Space>
          <Button onClick={onClose}>取消</Button>
          <Button type="primary" onClick={handleSave}>
            保存
          </Button>
        </Space>
      }
    >
      {node && (
        <Form form={form} layout="vertical">
          <Form.Item label="节点名称" name="name" rules={[{ required: true }]}>
            <Input />
          </Form.Item>

          {renderConfigFields(node.type as NodeType)}
        </Form>
      )}
    </Drawer>
  )
}

export default NodeConfigPanel
