import { useCallback, useEffect, useState } from 'react'
import {
  Table,
  Button,
  Space,
  Tag,
  Switch,
  Popconfirm,
  message,
  Modal,
  Form,
  Input,
  Select,
  Typography,
  Badge,
  Tooltip,
  Drawer,
} from 'antd'
import {
  PlusOutlined,
  EditOutlined,
  DeleteOutlined,
  SettingOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import type { ColumnsType } from 'antd/es/table'
import {
  listPlugins,
  createPlugin,
  updatePlugin,
  deletePlugin,
  testPlugin,
} from '@/api/plugin'
import type {
  Plugin,
  PluginType,
  PluginSourceType,
  PluginStatus,
  PluginTestResult,
  PluginCreateRequest,
} from '@/types/plugin'
import {
  PLUGIN_SOURCE_OPTIONS,
  PLUGIN_TYPE_OPTIONS,
  pluginSourceMeta,
  pluginTypeMeta,
} from './pluginMeta'
import { useAuthStore } from '@/stores/auth'

const { Title, Text } = Typography
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
    setLoading(true)
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
    fetchAll()
  }, [fetchAll])

  const openCreate = () => {
    setEditing(null)
    form.resetFields()
    form.setFieldsValue({
      plugin_type: 'tool',
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
      plugin_type: plugin.plugin_type,
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
        plugin_type: values.plugin_type,
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
          message.error('OpenAPI 规范 JSON 格式错误')
          return
        }
      }
      if (values.config_schema) {
        try {
          payload.config_schema = JSON.parse(values.config_schema)
        } catch {
          message.error('配置 Schema JSON 格式错误')
          return
        }
      }

      if (editing) {
        await updatePlugin(editing.id, payload)
        message.success('更新成功')
      } else {
        await createPlugin(payload)
        message.success('创建成功')
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
      message.success('删除成功')
      fetchAll()
    } catch {
      // interceptor handles error toast
    }
  }

  const handleToggleStatus = async (plugin: Plugin, checked: boolean) => {
    try {
      await updatePlugin(plugin.id, { status: (checked ? 'active' : 'disabled') as PluginStatus })
      message.success(checked ? '已启用' : '已禁用')
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

  const columns: ColumnsType<Plugin> = [
    {
      title: '插件名称',
      dataIndex: 'name',
      key: 'name',
      render: (name, record) => (
        <Space direction="vertical" size={0}>
          <Space>
            <span style={{ fontWeight: 600 }}>{name}</span>
            {record.is_public && <Tag color="gold">公共</Tag>}
            {record.tenant_id === null && !record.is_public && (
              <Tag color="default">平台</Tag>
            )}
          </Space>
          {record.description && (
            <Text type="secondary" style={{ fontSize: 12 }}>
              {record.description}
            </Text>
          )}
        </Space>
      ),
    },
    {
      title: '类型',
      dataIndex: 'plugin_type',
      key: 'plugin_type',
      render: (t: PluginType) => {
        const meta = pluginTypeMeta(t)
        return (
          <Tooltip title={`${meta.description} 适用：${meta.useCases}`}>
            <Tag color={meta.color}>{meta.label}</Tag>
          </Tooltip>
        )
      },
    },
    {
      title: '接入方式',
      dataIndex: 'source_type',
      key: 'source_type',
      render: (s: PluginSourceType) => {
        const meta = pluginSourceMeta(s)
        return (
          <Tooltip title={`${meta.description} 适用：${meta.useCases}`}>
            <Tag color={meta.color}>{meta.label}</Tag>
          </Tooltip>
        )
      },
    },
    {
      title: '版本',
      dataIndex: 'version',
      key: 'version',
      render: (v) => <Text type="secondary">{v}</Text>,
    },
    {
      title: '作者',
      dataIndex: 'author',
      key: 'author',
      render: (a) => a || '—',
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (status: PluginStatus, record) => (
        <Space>
          <Badge
            status={status === 'active' ? 'success' : 'default'}
            text={status === 'active' ? '启用' : status === 'disabled' ? '禁用' : '待审核'}
          />
          {record.tenant_id !== null && (
            <Switch
              size="small"
              checked={status === 'active'}
              onChange={(c) => handleToggleStatus(record, c)}
            />
          )}
        </Space>
      ),
    },
    {
      title: '操作',
      key: 'actions',
      render: (_, record) => {
        const isPublic = record.tenant_id === null
        return (
          <Space>
            <Tooltip title="配置 / 端点 / 测试">
              <Button
                size="small"
                icon={<SettingOutlined />}
                onClick={() => navigate(`/plugins/${record.id}/config`)}
              >
                配置
              </Button>
            </Tooltip>
            <Tooltip title={isPublic ? '公共/平台插件不可编辑' : '编辑'}>
              <Button
                size="small"
                icon={<EditOutlined />}
                disabled={isPublic}
                onClick={() => openEdit(record)}
              />
            </Tooltip>
            <Tooltip title="测试连通性">
              <Button
                size="small"
                icon={<ThunderboltOutlined />}
                loading={testingId === record.id}
                onClick={() => handleTest(record)}
              />
            </Tooltip>
            <Popconfirm
              title="确认删除此插件？"
              onConfirm={() => handleDelete(record.id)}
              okText="删除"
              okButtonProps={{ danger: true }}
              cancelText="取消"
              disabled={isPublic}
            >
              <Tooltip title={isPublic ? '公共/平台插件不可删除' : '删除'}>
                <Button size="small" icon={<DeleteOutlined />} danger disabled={isPublic} />
              </Tooltip>
            </Popconfirm>
          </Space>
        )
      },
    },
  ]

  return (
    <div>
      <div
        style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}
      >
        <Title level={4} style={{ margin: 0 }}>
          插件管理
        </Title>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
          新增插件
        </Button>
      </div>

      <Table
        columns={columns}
        dataSource={plugins}
        rowKey="id"
        loading={loading}
        pagination={{ pageSize: 20 }}
      />

      <Modal
        title={editing ? '编辑插件' : '新增插件'}
        open={modalOpen}
        onOk={handleSubmit}
        onCancel={() => setModalOpen(false)}
        confirmLoading={submitting}
        width={640}
        destroyOnClose
      >
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="插件名称" rules={[{ required: true }]}>
            <Input placeholder="如：天气查询插件" />
          </Form.Item>
          <Space style={{ display: 'flex' }} size="large" wrap>
            <Form.Item
              name="plugin_type"
              label="能力形态（做什么）"
              tooltip="工具：可被 Agent 调用的动作；连接器：对接外部系统；处理器：数据转换加工。"
              rules={[{ required: true }]}
            >
              <Select options={PLUGIN_TYPE_OPTIONS} style={{ width: 220 }} />
            </Form.Item>
            <Form.Item
              name="source_type"
              label="接入方式（怎么接）"
              tooltip="HTTP / OpenAPI 为当前可用方式；MCP 与 Skill 为类型占位，执行器实现属二期。"
              rules={[{ required: true }]}
            >
              <Select options={PLUGIN_SOURCE_OPTIONS} style={{ width: 200 }} />
            </Form.Item>
          </Space>
          <Form.Item name="version" label="版本" rules={[{ required: true }]}>
            <Input style={{ width: 160 }} />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <TextArea rows={2} placeholder="插件功能说明" />
          </Form.Item>
          <Form.Item
            name="api_spec"
            label="OpenAPI 规范（JSON，可选）"
            extra="提供后将自动解析生成插件端点"
          >
            <TextArea rows={4} placeholder='{"openapi":"3.0.0","servers":[{"url":"https://..."}],"paths":{...}}' />
          </Form.Item>
          <Form.Item name="config_schema" label="配置 Schema（JSON，可选）">
            <TextArea rows={3} placeholder='{"type":"object","properties":{"api_key":{"type":"string"}}}' />
          </Form.Item>
          <Space size="large">
            <Form.Item name="status" label="状态">
              <Select
                style={{ width: 160 }}
                options={[
                  { value: 'active', label: '启用' },
                  { value: 'disabled', label: '禁用' },
                  { value: 'pending_review', label: '待审核' },
                ]}
              />
            </Form.Item>
            {isPlatformAdmin && (
              <Form.Item
                name="is_public"
                label="设为公共插件"
                valuePropName="checked"
                extra="公共插件对所有租户可见可用"
              >
                <Switch />
              </Form.Item>
            )}
          </Space>
        </Form>
      </Modal>

      <Drawer
        title="连通性测试结果"
        open={testResult !== null}
        onClose={() => setTestResult(null)}
        width={480}
      >
        {testResult && (
          <Space direction="vertical" style={{ width: '100%' }}>
            <Badge
              status={testResult.success ? 'success' : 'error'}
              text={testResult.success ? '连通成功' : '连通失败'}
            />
            <div>状态码：{testResult.status_code ?? '—'}</div>
            <div>耗时：{testResult.latency_ms ?? '—'} ms</div>
            {testResult.error && (
              <Text type="danger">错误：{testResult.error}</Text>
            )}
            <Text type="secondary">返回数据：</Text>
            <TextArea
              readOnly
              rows={8}
              value={
                typeof testResult.data === 'string'
                  ? testResult.data
                  : JSON.stringify(testResult.data, null, 2)
              }
            />
          </Space>
        )}
      </Drawer>
    </div>
  )
}
