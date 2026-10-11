import { useCallback, useEffect, useState } from 'react'
import {
  Badge,
  Button,
  Collapse,
  Drawer,
  Empty,
  Form,
  Input,
  message,
  Modal,
  Popconfirm,
  Space,
  Spin,
  Switch,
  Tag,
  Tooltip,
  Typography,
} from 'antd'
import {
  ArrowRightOutlined,
  DeleteOutlined,
  EditOutlined,
  PlusOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import {
  createPlugin,
  deletePlugin,
  listPlugins,
  testPlugin,
  updatePlugin,
} from '@/api/plugin'
import type {
  Plugin,
  PluginCreateRequest,
  PluginStatus,
  PluginTestResult,
} from '@/types/plugin'
import { useAuthStore } from '@/stores/auth'
import { getPluginReadiness } from './pluginExperience'
import './PluginExperience.css'

const { Paragraph, Text, Title } = Typography
const { TextArea } = Input

export default function PluginList() {
  const navigate = useNavigate()
  const isPlatformAdmin = useAuthStore((s) => s.user?.is_platform_admin)
  const [plugins, setPlugins] = useState<Plugin[]>([])
  const [loading, setLoading] = useState(true)
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<Plugin | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [testResult, setTestResult] = useState<PluginTestResult | null>(null)
  const [testingId, setTestingId] = useState<string | null>(null)
  const [form] = Form.useForm()

  const fetchAll = useCallback(async () => {
    try {
      const res = await listPlugins({ page: 1, page_size: 200, include_public: true })
      setPlugins(res.data?.items ?? [])
    } catch {
      // interceptor handles error toast
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    let active = true
    void Promise.resolve().then(() => {
      if (active) return fetchAll()
    })
    return () => {
      active = false
    }
  }, [fetchAll])

  const openCreate = () => {
    setEditing(null)
    form.resetFields()
    form.setFieldsValue({
      source_type: 'http',
      version: '1.0.0',
      status: 'active',
      is_public: false,
    })
    setModalOpen(true)
  }

  const openEdit = (plugin: Plugin) => {
    setEditing(plugin)
    form.setFieldsValue({
      name: plugin.name,
      source_type: plugin.source_type,
      version: plugin.version,
      description: plugin.description,
      status: plugin.status,
      is_public: plugin.is_public,
      api_spec: plugin.api_spec ? JSON.stringify(plugin.api_spec, null, 2) : '',
      config_schema: plugin.config_schema
        ? JSON.stringify(plugin.config_schema, null, 2)
        : '',
    })
    setModalOpen(true)
  }

  const handleSubmit = async () => {
    const values = await form.validateFields()
    setSubmitting(true)
    try {
      const payload: PluginCreateRequest = {
        name: values.name,
        source_type: values.source_type,
        version: values.version,
        description: values.description,
        status: values.status,
        is_public: Boolean(values.is_public) && isPlatformAdmin,
      }
      if (values.api_spec) {
        try {
          payload.api_spec = JSON.parse(values.api_spec)
        } catch {
          message.error('服务说明格式不正确，请检查 JSON 内容')
          return
        }
      }
      if (values.config_schema) {
        try {
          payload.config_schema = JSON.parse(values.config_schema)
        } catch {
          message.error('连接表单格式不正确，请检查 JSON 内容')
          return
        }
      }

      if (editing) {
        await updatePlugin(editing.id, payload)
        message.success('插件信息已保存')
      } else {
        await createPlugin(payload)
        message.success('插件已添加，接下来完成连接并试用')
      }
      setModalOpen(false)
      fetchAll()
    } catch {
      // interceptor handles error toast；validateFields 抛错时静默
    } finally {
      setSubmitting(false)
    }
  }

  const handleDelete = async (id: string) => {
    try {
      await deletePlugin(id)
      message.success('插件已删除')
      fetchAll()
    } catch {
      // interceptor handles error toast
    }
  }

  const handleToggleStatus = async (plugin: Plugin, checked: boolean) => {
    try {
      await updatePlugin(plugin.id, {
        status: (checked ? 'active' : 'disabled') as PluginStatus,
      })
      message.success(checked ? '插件已开启' : '插件已暂停')
      fetchAll()
    } catch {
      // interceptor handles error toast
    }
  }

  const handleTest = async (plugin: Plugin) => {
    setTestingId(plugin.id)
    setTestResult(null)
    try {
      const res = await testPlugin(plugin.id)
      setTestResult(res.data ?? null)
    } catch {
      // interceptor handles error toast
    } finally {
      setTestingId(null)
    }
  }

  return (
    <div className="plugin-experience-page">
      <section className="plugin-hero">
        <div className="plugin-hero__copy">
          <Text className="plugin-eyebrow">Agent 能力中心</Text>
          <Title level={1}>让 Agent 连接你正在使用的服务</Title>
          <Paragraph>
            添加一个插件，Agent 就能在对话中查询信息、创建内容或执行操作。你只需要完成连接、试用，再选择给哪些 Agent 使用。
          </Paragraph>
          <Button
            type="primary"
            size="large"
            icon={<PlusOutlined />}
            aria-label="添加插件"
            onClick={openCreate}
          >
            添加插件
          </Button>
        </div>

        <div className="capability-route" aria-label="插件使用流程">
          <div className="capability-route__node">
            <span className="capability-route__index">1</span>
            <strong>你的服务</strong>
            <small>已有的业务系统</small>
          </div>
          <ArrowRightOutlined className="capability-route__arrow" />
          <div className="capability-route__node capability-route__node--active">
            <span className="capability-route__index">2</span>
            <strong>插件</strong>
            <small>连接并说明能做什么</small>
          </div>
          <ArrowRightOutlined className="capability-route__arrow" />
          <div className="capability-route__node">
            <span className="capability-route__index">3</span>
            <strong>Agent</strong>
            <small>在对话中按需使用</small>
          </div>
        </div>
      </section>

      <section className="plugin-library" aria-labelledby="plugin-library-title">
        <div className="plugin-section-heading">
          <div>
            <Text className="plugin-eyebrow">已添加</Text>
            <Title id="plugin-library-title" level={3}>插件能力</Title>
          </div>
          <Text type="secondary">开启的插件可在 Agent 编辑页按能力授权</Text>
        </div>

        {loading ? (
          <div className="plugin-loading"><Spin /></div>
        ) : plugins.length === 0 ? (
          <div className="plugin-empty">
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={
                <Space orientation="vertical" size={4}>
                  <Text strong>还没有插件</Text>
                  <Text type="secondary">先添加一个你熟悉的服务，完成后就能把它交给 Agent 使用。</Text>
                </Space>
              }
            >
              <Button type="primary" onClick={openCreate}>添加第一个插件</Button>
            </Empty>
          </div>
        ) : (
          <div className="plugin-card-grid">
            {plugins.map((plugin) => {
              const readiness = getPluginReadiness(plugin)
              const isPlatformPlugin = plugin.tenant_id === null
              const preview = plugin.endpoints?.slice(0, 2) ?? []
              return (
                <article className="plugin-card" key={plugin.id}>
                  <div className="plugin-card__topline">
                    <span className={`plugin-readiness plugin-readiness--${readiness.tone}`}>
                      <span className="plugin-readiness__dot" />
                      {readiness.label}
                    </span>
                    {isPlatformPlugin ? (
                      <Tag bordered={false}>平台提供</Tag>
                    ) : (
                      <Switch
                        size="small"
                        aria-label={`${plugin.name}${plugin.status === 'active' ? '已开启' : '已暂停'}`}
                        checked={plugin.status === 'active'}
                        onChange={(checked) => handleToggleStatus(plugin, checked)}
                      />
                    )}
                  </div>

                  <div className="plugin-card__identity">
                    <div className="plugin-card__mark">{plugin.name.slice(0, 1).toUpperCase()}</div>
                    <div>
                      <Title level={4}>{plugin.name}</Title>
                      <Paragraph ellipsis={{ rows: 2 }}>
                        {plugin.description || '还没有说明这个插件能帮助 Agent 做什么。'}
                      </Paragraph>
                    </div>
                  </div>

                  <div className="plugin-card__abilities">
                    <Text className="plugin-card__abilities-label">
                      {plugin.endpoints?.length || 0} 项可用能力
                    </Text>
                    {preview.length > 0 ? preview.map((endpoint) => (
                      <div className="plugin-ability-preview" key={endpoint.id}>
                        <span>{endpoint.description || '未命名能力'}</span>
                        <code>{endpoint.method.toUpperCase()} {endpoint.endpoint}</code>
                      </div>
                    )) : (
                      <Text type="secondary">添加能力后，Agent 才知道可以用它完成哪些事情。</Text>
                    )}
                  </div>

                  <div className="plugin-card__actions">
                    <Button type="primary" onClick={() => navigate(`/plugins/${plugin.id}/config`)}>
                      {readiness.action}
                    </Button>
                    <Space size={4}>
                      <Tooltip title="快速检查连接">
                        <Button
                          aria-label={`检查 ${plugin.name} 的连接`}
                          icon={<ThunderboltOutlined />}
                          loading={testingId === plugin.id}
                          onClick={() => handleTest(plugin)}
                        />
                      </Tooltip>
                      <Tooltip title={isPlatformPlugin ? '平台插件不可编辑' : '编辑基本信息'}>
                        <Button
                          aria-label={`编辑 ${plugin.name}`}
                          icon={<EditOutlined />}
                          disabled={isPlatformPlugin}
                          onClick={() => openEdit(plugin)}
                        />
                      </Tooltip>
                      <Popconfirm
                        title="删除这个插件？"
                        description="删除后，Agent 将无法再使用它的能力。"
                        onConfirm={() => handleDelete(plugin.id)}
                        okText="删除"
                        okButtonProps={{ danger: true }}
                        cancelText="保留"
                        disabled={isPlatformPlugin}
                      >
                        <Tooltip title={isPlatformPlugin ? '平台插件不可删除' : '删除'}>
                          <Button
                            aria-label={`删除 ${plugin.name}`}
                            icon={<DeleteOutlined />}
                            danger
                            disabled={isPlatformPlugin}
                          />
                        </Tooltip>
                      </Popconfirm>
                    </Space>
                  </div>
                </article>
              )
            })}
          </div>
        )}
      </section>

      <Modal
        title={editing ? '编辑插件信息' : '添加插件'}
        open={modalOpen}
        onOk={handleSubmit}
        onCancel={() => setModalOpen(false)}
        okText={editing ? '保存信息' : '添加并继续'}
        cancelText="取消"
        confirmLoading={submitting}
        width={680}
        destroyOnHidden
      >
        <div className="plugin-modal-intro">
          {editing
            ? '修改插件的名称和用途说明。连接信息与能力设置会保留。'
            : '先告诉大家这个插件能做什么。添加后，再完成连接和试用。'}
        </div>
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="插件名称" rules={[{ required: true, message: '请填写插件名称' }]}>
            <Input placeholder="例如：客户信息查询" />
          </Form.Item>
          <Form.Item name="description" label="它能帮助 Agent 做什么？">
            <TextArea
              rows={3}
              placeholder="例如：根据客户名称查询联系人、订单和最近一次沟通记录"
              showCount
              maxLength={240}
            />
          </Form.Item>
          <Form.Item name="source_type" hidden><Input /></Form.Item>
          <Form.Item name="version" hidden><Input /></Form.Item>
          <Form.Item name="status" hidden><Input /></Form.Item>

          {isPlatformAdmin && (
            <Form.Item
              name="is_public"
              label="提供给所有组织使用"
              valuePropName="checked"
              extra="开启后，平台中的所有组织都能看到并配置这个插件。"
            >
              <Switch />
            </Form.Item>
          )}

          <Collapse
            ghost
            className="plugin-advanced-collapse"
            items={[{
              key: 'advanced',
              label: '高级设置',
              children: (
                <>
                  <Form.Item
                    name="api_spec"
                    label="从服务说明自动识别能力"
                    extra="如果服务提供 OpenAPI JSON，可粘贴到这里；保存后会自动识别可用操作。也可以稍后手动添加。"
                  >
                    <TextArea
                      rows={6}
                      className="plugin-code-field"
                      placeholder='{"openapi":"3.0.0","servers":[{"url":"https://..."}],"paths":{...}}'
                    />
                  </Form.Item>
                  <Form.Item
                    name="config_schema"
                    label="自定义连接表单"
                    extra="仅在需要自定义连接字段时填写 JSON Schema。多数插件可以留空。"
                  >
                    <TextArea
                      rows={4}
                      className="plugin-code-field"
                      placeholder='{"type":"object","properties":{"api_key":{"type":"string"}}}'
                    />
                  </Form.Item>
                </>
              ),
            }]}
          />
        </Form>
      </Modal>

      <Drawer
        title="连接检查结果"
        open={testResult !== null}
        onClose={() => setTestResult(null)}
        size="large"
      >
        {testResult && (
          <Space direction="vertical" style={{ width: '100%' }}>
            <Badge
              status={testResult.success ? 'success' : 'error'}
              text={testResult.success ? '服务可以访问' : '暂时无法访问服务'}
            />
            <div>状态码：{testResult.status_code ?? '—'}</div>
            <div>耗时：{testResult.latency_ms ?? '—'} ms</div>
            {testResult.error && <Text type="danger">原因：{testResult.error}</Text>}
            <Text type="secondary">服务返回内容</Text>
            <TextArea
              readOnly
              rows={8}
              className="plugin-code-field"
              value={typeof testResult.data === 'string'
                ? testResult.data
                : JSON.stringify(testResult.data, null, 2)}
            />
          </Space>
        )}
      </Drawer>
    </div>
  )
}
