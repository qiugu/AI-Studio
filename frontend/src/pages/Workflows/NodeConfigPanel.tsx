import React from 'react'
import { Drawer, Form, Input, Select, InputNumber, Button, Space, message } from 'antd'
import type { Node } from 'reactflow'
import { listModels } from '@/api/ai-model'
import { listKnowledgeBases } from '@/api/knowledge'
import { listPrompts } from '@/api/prompt'
import type { AIModel } from '@/types/ai-model'
import type { KnowledgeBase } from '@/types/knowledge'
import type { Prompt } from '@/types/prompt'
import type { NodeType, WorkflowNodeConfig } from '../../types/workflow'

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
  const modelsLoading = visible && node?.type === 'llm' && !modelsLoaded
  const promptsLoading = visible && node?.type === 'llm' && !promptsLoaded
  const knowledgeBasesLoading = visible && node?.type === 'knowledge' && !knowledgeBasesLoaded
  const selectedModelId = Form.useWatch('model_id', form)
  const selectedModel = models.find((model) => model.id === selectedModelId)
  const selectedPromptId = Form.useWatch('prompt_id', form)
  const selectedPrompt = prompts.find((prompt) => prompt.id === selectedPromptId)

  React.useEffect(() => {
    if (node) {
      form.resetFields()
      form.setFieldsValue({
        name: node.data.name,
        ...node.data.config,
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

  const handleSave = () => {
    form.validateFields().then((values) => {
      const { name, ...config } = values
      onSave(node!.id, {
        name,
        config,
      })
      message.success('节点配置已保存')
      onClose()
    })
  }

  const renderConfigFields = (nodeType: NodeType) => {
    switch (nodeType) {
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
                placeholder="result = input_data['value'] * 2\nreturn result"
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
                        <Select style={{ width: 120 }}>
                          <Select.Option value="static">静态值</Select.Option>
                          <Select.Option value="context">上下文引用</Select.Option>
                          <Select.Option value="expression">表达式</Select.Option>
                        </Select>
                      </Form.Item>
                      <Form.Item {...restField} name={[name, 'value']}>
                        <Input placeholder="值" />
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
