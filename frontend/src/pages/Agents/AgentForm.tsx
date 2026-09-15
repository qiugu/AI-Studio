/**
 * Agent创建/编辑表单页面
 *
 * 「工具能力」区块是 Agent 的**授权面**：用户从服务端裁剪过的插件目录中显式挑选
 * 「插件 → 端点」，选中的集合即该 Agent 的能力边界。未选中的插件不会被注入工具池，
 * 也不占用模型的上下文。
 */

import { useState, useEffect } from 'react'
import {
  Form,
  Input,
  Button,
  Select,
  InputNumber,
  Card,
  Space,
  message,
  Spin,
  Checkbox,
  Tag,
  Switch,
  Tooltip,
  Empty,
  Typography,
  Modal,
  Alert,
} from 'antd'
import { useNavigate, useParams } from 'react-router-dom'
import * as agentApi from '@/api/agent'
import * as aiModelApi from '@/api/ai-model'
import type {
  AgentCreateRequest,
  AgentStatus,
  AgentUpdateRequest,
  ToolCatalogPlugin,
} from '@/types/agent'
import { type AIModel } from '@/types/ai-model'
import { pluginSourceMeta } from '@/pages/Plugins/pluginMeta'
import {
  isDestructiveMethod,
  missingSelectionKeys,
  selectionKey,
  selectionsToToolPayload,
  toolsToSelectionKeys,
} from './agentToolBinding'

const { TextArea } = Input
const { Text } = Typography

/** 表单字段：对应 Agent 基础信息；工具授权走独立的 selectedKeys 状态。 */
interface AgentFormValues {
  name: string
  description?: string
  avatar?: string
  system_prompt?: string
  model_id: number
  temperature?: number
  max_tokens?: number
  status?: AgentStatus
}

export default function AgentForm() {
  const navigate = useNavigate()
  const { agentId } = useParams()
  const isEdit = Boolean(agentId)
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [models, setModels] = useState<AIModel[]>([])

  // 工具授权态
  const [catalog, setCatalog] = useState<ToolCatalogPlugin[]>([])
  // 目录在挂载时即开始加载，故初值为 true：避免在 effect 内同步 setState
  // （同步 setState 会触发 react-hooks/set-state-in-effect，且本身也是多余的一次渲染）
  const [catalogLoading, setCatalogLoading] = useState(true)
  const [catalogError, setCatalogError] = useState(false)
  const [selectedKeys, setSelectedKeys] = useState<string[]>([])
  const [showDestructive, setShowDestructive] = useState(false)

  const loadModels = async () => {
    try {
      const { data } = await aiModelApi.listModels({ page: 1, page_size: 100 })
      setModels(data.items)
    } catch (error) {
      console.error('Failed to load models:', error)
      message.error('加载AI模型列表失败')
    }
  }

  /** 取可绑定插件目录。返回目录，便于调用方在同一次流程里完成回填。 */
  const loadCatalog = async (): Promise<ToolCatalogPlugin[]> => {
    try {
      const { data } = await agentApi.getToolCatalog()
      setCatalog(data)
      setCatalogError(false)
      return data
    } catch (error) {
      console.error('Failed to load tool catalog:', error)
      // 目录拉取失败时必须阻止提交：提交会以空目录重建工具清单，
      // 从而静默清空该 Agent 已有的全部插件授权。
      setCatalogError(true)
      message.error('加载可绑定插件目录失败')
      return []
    } finally {
      setCatalogLoading(false)
    }
  }

  /** 加载 Agent 基本信息，并按目录回填已授权的工具选择项。 */
  const loadAgent = async (catalogData: ToolCatalogPlugin[]) => {
    setLoading(true)
    try {
      const { data } = await agentApi.getAgent(agentId || '')
      form.setFieldsValue({
        name: data.name,
        description: data.description,
        avatar: data.avatar,
        system_prompt: data.system_prompt,
        model_id: data.model_id,
        temperature: data.temperature,
        max_tokens: data.max_tokens,
        status: data.status,
      })
      setSelectedKeys(toolsToSelectionKeys(data.tools, catalogData))
    } catch (error) {
      console.error('Failed to load agent:', error)
      message.error('加载Agent信息失败')
    } finally {
      setLoading(false)
    }
  }

  /** 先取目录再取 Agent：回填依赖目录（端点路径 → 端点 id），顺序不可颠倒。 */
  const loadCatalogThenAgent = async () => {
    const catalogData = await loadCatalog()
    if (isEdit) {
      await loadAgent(catalogData)
    }
  }

  useEffect(() => {
    loadModels()
    void loadCatalogThenAgent()
  }, [agentId])

  const addSelection = (key: string) => {
    setSelectedKeys((prev) => (prev.includes(key) ? prev : [...prev, key]))
  }

  const removeSelection = (key: string) => {
    setSelectedKeys((prev) => prev.filter((item) => item !== key))
  }

  /**
   * 切换单个端点授权。
   *
   * 破坏性端点须经二次确认：勾选动作本身即一次显式授权，落库时写入
   * `allow_destructive: true`，因此后端门禁仍具约束力，而不是被前端悄悄绕过。
   */
  const handleToggleEndpoint = (
    plugin: ToolCatalogPlugin,
    endpointId: string,
    checked: boolean
  ) => {
    const key = selectionKey(plugin.id, endpointId)
    if (!checked) {
      removeSelection(key)
      return
    }

    const endpoint = plugin.endpoints.find((item) => item.id === endpointId)
    if (!endpoint || !isDestructiveMethod(endpoint.method)) {
      addSelection(key)
      return
    }

    Modal.confirm({
      title: '确认授权破坏性端点？',
      content: (
        <div>
          <div>
            端点：<Text code>{`${endpoint.method.toUpperCase()} ${endpoint.endpoint}`}</Text>
          </div>
          <div style={{ marginTop: 8 }}>
            该操作可能删除或覆盖外部系统中的数据。授权后，模型可在对话中直接调用它。
          </div>
        </div>
      ),
      okText: '确认授权',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: () => addSelection(key),
    })
  }

  const handleSubmit = async (values: AgentFormValues) => {
    setSubmitting(true)
    try {
      const tools = selectionsToToolPayload(selectedKeys, catalog)

      if (isEdit) {
        const updateData: AgentUpdateRequest = {
          name: values.name,
          description: values.description,
          avatar: values.avatar,
          system_prompt: values.system_prompt,
          model_id: values.model_id,
          temperature: values.temperature,
          max_tokens: values.max_tokens,
          status: values.status,
          tools,
        }
        await agentApi.updateAgent(agentId || '', updateData)
        message.success('Agent已更新')
      } else {
        const createData: AgentCreateRequest = {
          name: values.name,
          description: values.description,
          avatar: values.avatar,
          system_prompt: values.system_prompt,
          model_id: values.model_id,
          temperature: values.temperature || 0.7,
          max_tokens: values.max_tokens || 2000,
          status: values.status || 'draft',
          tools,
        }
        await agentApi.createAgent(createData)
        message.success('Agent已创建')
      }

      navigate('/agents')
    } catch (error) {
      console.error('Failed to submit:', error)
      message.error(isEdit ? '更新Agent失败' : '创建Agent失败')
    } finally {
      setSubmitting(false)
    }
  }

  const missingKeys = missingSelectionKeys(selectedKeys, catalog)
  const destructiveSelectedCount = selectedKeys.filter((key) => {
    const [pluginId, endpointId] = key.split('::')
    const endpoint = catalog
      .find((plugin) => plugin.id === pluginId)
      ?.endpoints.find((item) => item.id === endpointId)
    return endpoint ? isDestructiveMethod(endpoint.method) : false
  }).length

  const renderCatalog = () => {
    if (catalogLoading) return <Spin />
    if (catalog.length === 0) {
      return (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={
            <span>
              暂无可绑定的插件。请先到「插件」页创建插件并配置端点，
              且接入方式为 HTTP / OpenAPI、状态为「启用」。
            </span>
          }
        />
      )
    }

    return (
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        {catalog.map((plugin) => {
          const sourceMeta = pluginSourceMeta(plugin.source_type)
          const visibleEndpoints = showDestructive
            ? plugin.endpoints
            : plugin.endpoints.filter((item) => !isDestructiveMethod(item.method))

          return (
            <div
              key={plugin.id}
              style={{
                border: '1px solid #f0f0f0',
                borderRadius: 8,
                padding: '12px 16px',
              }}
            >
              <Space size="small" wrap>
                <Text strong>{plugin.name}</Text>
                <Tooltip title={sourceMeta.description}>
                  <Tag color={sourceMeta.color}>{sourceMeta.label}</Tag>
                </Tooltip>
                {plugin.is_public && <Tag>平台内置</Tag>}
              </Space>
              {plugin.description && (
                <div style={{ marginTop: 4 }}>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {plugin.description}
                  </Text>
                </div>
              )}

              <div style={{ marginTop: 8 }}>
                {visibleEndpoints.length === 0 ? (
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    该插件仅含破坏性端点，已隐藏。开启上方开关后可选择。
                  </Text>
                ) : (
                  <Space direction="vertical" size={4}>
                    {visibleEndpoints.map((endpoint) => {
                      const destructive = isDestructiveMethod(endpoint.method)
                      const key = selectionKey(plugin.id, endpoint.id)
                      return (
                        <Checkbox
                          key={key}
                          checked={selectedKeys.includes(key)}
                          onChange={(event) =>
                            handleToggleEndpoint(plugin, endpoint.id, event.target.checked)
                          }
                        >
                          <Space size="small">
                            <Text code>{endpoint.method.toUpperCase()}</Text>
                            <span>{endpoint.endpoint}</span>
                            {destructive && <Tag color="red">破坏性</Tag>}
                            {endpoint.description && (
                              <Text type="secondary" style={{ fontSize: 12 }}>
                                {endpoint.description}
                              </Text>
                            )}
                          </Space>
                        </Checkbox>
                      )
                    })}
                  </Space>
                )}
              </div>
            </div>
          )
        })}
      </Space>
    )
  }

  return (
    <div style={{ padding: '24px' }}>
      <Card title={isEdit ? '编辑Agent' : '创建Agent'}>
        <Spin spinning={loading}>
          <Form
            form={form}
            layout="vertical"
            onFinish={handleSubmit}
            initialValues={{
              temperature: 0.7,
              max_tokens: 2000,
              status: 'draft',
            }}
          >
            <Form.Item
              label="Agent名称"
              name="name"
              rules={[{ required: true, message: '请输入Agent名称' }]}
            >
              <Input placeholder="请输入Agent名称" maxLength={255} />
            </Form.Item>

            <Form.Item label="描述" name="description">
              <TextArea placeholder="请输入Agent描述" rows={3} maxLength={500} />
            </Form.Item>

            <Form.Item label="头像URL" name="avatar">
              <Input placeholder="请输入头像URL" maxLength={255} />
            </Form.Item>

            <Form.Item label="系统提示词" name="system_prompt">
              <TextArea placeholder="请输入系统提示词" rows={5} />
            </Form.Item>

            <Form.Item
              label="AI模型"
              name="model_id"
              rules={[{ required: true, message: '请选择AI模型' }]}
            >
              <Select placeholder="请选择AI模型">
                {models.map((model) => (
                  <Select.Option key={model.id} value={model.id}>
                    {model.display_name}
                  </Select.Option>
                ))}
              </Select>
            </Form.Item>

            <Form.Item label="Temperature" name="temperature">
              <InputNumber min={0} max={2} step={0.1} />
            </Form.Item>

            <Form.Item label="最大Token数" name="max_tokens">
              <InputNumber min={1} max={32000} />
            </Form.Item>

            <Form.Item label="状态" name="status">
              <Select>
                <Select.Option value="draft">草稿</Select.Option>
                <Select.Option value="published">已发布</Select.Option>
                <Select.Option value="archived">已归档</Select.Option>
              </Select>
            </Form.Item>

            <Card
              type="inner"
              title="工具能力"
              extra={
                <Space size="small">
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    显示破坏性端点
                  </Text>
                  <Switch checked={showDestructive} onChange={setShowDestructive} />
                </Space>
              }
              style={{ marginBottom: 24 }}
            >
              <Text type="secondary" style={{ fontSize: 12 }}>
                只有在此勾选的端点才会暴露给该 Agent；未勾选的插件不会被注入工具池。
              </Text>

              {catalogError && (
                <Alert
                  type="error"
                  showIcon
                  style={{ marginTop: 12 }}
                  message="可绑定插件目录加载失败，暂不可提交"
                  description="目录是工具清单的唯一依据，加载失败时保存会误清空该 Agent 已有的插件授权。请刷新页面重试。"
                />
              )}

              {missingKeys.length > 0 && (
                <Alert
                  type="warning"
                  showIcon
                  style={{ marginTop: 12 }}
                  message={`有 ${missingKeys.length} 个已授权插件或端点在目录中已失效`}
                  description="对应的插件可能已被删除、停用，或端点已被移除。保存后这些授权将不再生效，请重新选择。"
                />
              )}

              {destructiveSelectedCount > 0 && (
                <Alert
                  type="error"
                  showIcon
                  style={{ marginTop: 12 }}
                  message={`已授权 ${destructiveSelectedCount} 个破坏性端点`}
                  description="这些操作可能删除或覆盖外部系统中的数据，请确认确有必要。"
                />
              )}

              <div style={{ marginTop: 12 }}>{renderCatalog()}</div>
            </Card>

            <Form.Item>
              <Space>
                <Button
                  type="primary"
                  htmlType="submit"
                  loading={submitting}
                  disabled={catalogError}
                >
                  {isEdit ? '更新' : '创建'}
                </Button>
                <Button onClick={() => navigate('/agents')}>取消</Button>
              </Space>
            </Form.Item>
          </Form>
        </Spin>
      </Card>
    </div>
  )
}
