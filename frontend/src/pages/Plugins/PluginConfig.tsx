import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Card,
  Form,
  Input,
  Select,
  Switch,
  InputNumber,
  Button,
  Space,
  Typography,
  Table,
  Modal,
  message,
  Badge,
  Popconfirm,
  Alert,
  Tooltip,
  Collapse,
} from 'antd'
import {
  ArrowLeftOutlined,
  SaveOutlined,
  PlusOutlined,
  EditOutlined,
  DeleteOutlined,
  ThunderboltOutlined,
  ImportOutlined,
  QuestionCircleOutlined,
  CheckOutlined,
  ArrowRightOutlined,
} from '@ant-design/icons'
import { useNavigate, useParams } from 'react-router-dom'
import type { ColumnsType } from 'antd/es/table'
import {
  getPlugin,
  getPluginConfig,
  updatePluginConfig,
  listEndpoints,
  addEndpoint,
  updateEndpoint,
  deleteEndpoint,
  importEndpoints,
  testPlugin,
} from '@/api/plugin'
import type {
  Plugin,
  PluginEndpoint,
  PluginConfigItem,
  PluginTestResult,
  PluginEndpointCreateRequest,
  PluginEndpointUpdateRequest,
} from '@/types/plugin'
import {
  buildConnectionConfigItems,
  getSetupProgress,
  splitConnectionConfig,
} from './pluginExperience'
import './PluginExperience.css'

const { Title, Text } = Typography
const { TextArea } = Input
const { Password } = Input

const HTTP_METHODS = ['GET', 'POST', 'PUT', 'DELETE', 'PATCH']

type JsonParseResult =
  | { ok: true; value: unknown }
  | { ok: false; error: string }

const okValue = (value: unknown): JsonParseResult => ({ ok: true, value })
const failParse = (error: string): JsonParseResult => ({ ok: false, error })

function isParseError(r: JsonParseResult): r is { ok: false; error: string } {
  return !r.ok
}

/** 解析 JSON 文本；失败时返回错误信息（含位置）便于定位，成功返回对象。 */
function parseJsonField(
  text: string,
  opts: { required?: boolean; allowEmpty?: boolean } = {}
): JsonParseResult {
  const { required = false, allowEmpty = true } = opts
  if (!text || !text.trim()) {
    if (required) return failParse('内容不能为空')
    if (allowEmpty) return okValue(null)
    return okValue(null)
  }
  try {
    return okValue(JSON.parse(text))
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e)
    return failParse(`JSON 语法错误：${msg}`)
  }
}

/** 多行 JSON 输入区：带标题、说明、示例与实时格式校验反馈。 */
function JsonField({
  label,
  tooltip,
  placeholder,
  example,
  value,
  onChange,
  rows = 3,
}: {
  label: string
  tooltip?: string
  placeholder?: string
  example?: string
  value: string
  onChange: (v: string) => void
  rows?: number
}) {
  const parsed = parseJsonField(value)
  const error = isParseError(parsed) ? parsed.error : null
  return (
    <Form.Item
      label={
        <Space size={4}>
          <span>{label}</span>
          {tooltip && (
            <Tooltip title={tooltip}>
              <QuestionCircleOutlined style={{ color: '#999' }} />
            </Tooltip>
          )}
        </Space>
      }
      validateStatus={error ? 'error' : undefined}
      help={
        error ? (
          error
        ) : (
          <span style={{ color: '#999' }}>
            标准 JSON 格式（双引号、无尾随逗号）。点此查看示例：
            <Typography.Link
              style={{ marginLeft: 4 }}
              onClick={() => onChange(example ?? '')}
            >
              填入示例
            </Typography.Link>
          </span>
        )
      }
    >
      <TextArea
        rows={rows}
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        style={error ? { borderColor: '#ff4d4f' } : undefined}
      />
    </Form.Item>
  )
}

/** 根据 JSON Schema 渲染单个配置字段 */
function renderSchemaField(propName: string, prop: Record<string, unknown>) {
  const type = prop.type as string
  const title = (prop.title as string) || propName
  const isSecret = /key|secret|token|password/i.test(`${propName}${title}`)

  let control: React.ReactNode
  switch (type) {
    case 'boolean':
      control = <Switch />
      break
    case 'number':
    case 'integer':
      control = <InputNumber style={{ width: '100%' }} />
      break
    case 'object':
    case 'array':
      control = <TextArea rows={4} placeholder="JSON 格式" />
      break
    default:
      control = isSecret ? <Password placeholder="敏感信息" /> : <Input />
  }

  return (
    <Form.Item
      key={propName}
      name={propName}
      label={title}
      valuePropName={type === 'boolean' ? 'checked' : 'value'}
      extra={prop.description as string}
    >
      {control}
    </Form.Item>
  )
}

export default function PluginConfig() {
  const navigate = useNavigate()
  const { id } = useParams<{ id: string }>()
  const [plugin, setPlugin] = useState<Plugin | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm()
  const [connectionForm] = Form.useForm()

  const [hasSchema, setHasSchema] = useState(false)
  const [rawConfig, setRawConfig] = useState('{}')
  const [hasConnection, setHasConnection] = useState(false)
  const [hasExistingApiKey, setHasExistingApiKey] = useState(false)

  // 端点管理
  const [endpoints, setEndpoints] = useState<PluginEndpoint[]>([])
  const [epModalOpen, setEpModalOpen] = useState(false)
  const [editingEp, setEditingEp] = useState<PluginEndpoint | null>(null)
  const [epSubmitting, setEpSubmitting] = useState(false)
  const [epForm] = Form.useForm()
  // 端点弹窗内 JSON 字段的受控文本（便于实时校验与示例填充）
  const [epHeaders, setEpHeaders] = useState('')
  const [epReqSchema, setEpReqSchema] = useState('')
  const [epRespSchema, setEpRespSchema] = useState('')

  // 记录各配置项「加载时是否已设置真实值」，用于保存时跳过「空值且原本已设置」的敏感字段，
  // 避免把脱敏/缺省值当成新值覆盖真实凭据（后端敏感项回显 value 为 null + has_value=true）。
  const hasValueRef = useRef<Record<string, boolean>>({})

  // 测试
  const [testModalOpen, setTestModalOpen] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<PluginTestResult | null>(null)
  const [testForm] = Form.useForm()
  const [testParamsText, setTestParamsText] = useState('')

  const load = useCallback(async () => {
    if (!id) return
    try {
      const [pluginRes, configRes] = await Promise.all([
        getPlugin(id),
        getPluginConfig(id),
      ])
      const p = pluginRes.data as Plugin
      setPlugin(p)
      const cfgItems: PluginConfigItem[] = configRes.data?.items ?? []
      const cfgMap: Record<string, unknown> = {}
      const nextHasValue: Record<string, boolean> = {}
      cfgItems.forEach((it) => {
        cfgMap[it.name] = it.value
        nextHasValue[it.name] = !!it.has_value
      })
      hasValueRef.current = nextHasValue
      setHasExistingApiKey(Boolean(nextHasValue.api_key))

      const servers = (p.api_spec?.servers as Array<{ url?: string }> | undefined) || []
      const hasServerInDefinition = servers.some((server) => Boolean(server.url))

      const schema = (p.config_schema as Record<string, unknown>) || null
      if (schema && (schema.properties as Record<string, unknown>)) {
        setHasSchema(true)
        form.setFieldsValue(cfgMap)
        setHasConnection(hasServerInDefinition || cfgItems.some((item) => item.has_value))
      } else {
        setHasSchema(false)
        const split = splitConnectionConfig(cfgItems)
        connectionForm.setFieldsValue({
          baseUrl: split.fields.baseUrl,
          apiKey: split.fields.apiKey,
          headersText: split.fields.headersText,
        })
        setRawConfig(JSON.stringify(split.advanced, null, 2))
        setHasConnection(hasServerInDefinition || Boolean(split.fields.baseUrl))
      }

      const epRes = await listEndpoints(id)
      setEndpoints(epRes.data ?? [])
    } catch {
      // interceptor handles error toast
    } finally {
      setLoading(false)
    }
  }, [connectionForm, form, id])

  useEffect(() => {
    let active = true
    void Promise.resolve().then(() => {
      if (active) return load()
    })
    return () => {
      active = false
    }
  }, [load])

  const schemaProperties = useMemo(() => {
    const schema = (plugin?.config_schema as Record<string, unknown>) || {}
    return (schema.properties as Record<string, Record<string, unknown>>) || {}
  }, [plugin])

// 与后端 _SECRET_KEY_HINTS 保持一致：命中即视为敏感项，回显不暴露、留空即保留。
const SECRET_NAME_HINTS = ['key', 'secret', 'token', 'password', 'pwd', 'credential', 'authorization', 'auth']
function isSecretName(name: string): boolean {
  const n = (name || '').toLowerCase()
  return SECRET_NAME_HINTS.some((h) => n.includes(h))
}

  const handleSaveConfig = async () => {
    if (!id) return
    setSaving(true)
    try {
      let items: PluginConfigItem[]
      if (hasSchema) {
        const values = form.getFieldsValue()
        items = Object.entries(schemaProperties).map(([name, prop]) => {
          const type = (prop as Record<string, unknown>).type as string
          let value = values[name]
          if ((type === 'object' || type === 'array') && typeof value === 'string') {
            try {
              value = JSON.parse(value || 'null')
            } catch {
              message.error(`配置项「${name}」JSON 格式错误`)
              setSaving(false)
              return null as unknown as PluginConfigItem
            }
          }
          // 敏感项：若用户留空且加载时本已设置真实值，则跳过发送，保留既有凭据
          // （后端敏感项回显为 value=null + has_value=true，空值不能作为新值覆盖）。
          const isEmpty = value === null || value === undefined || value === ''
          if (isSecretName(name) && isEmpty && hasValueRef.current[name]) {
            return null as unknown as PluginConfigItem
          }
          return { name, value }
        }).filter(Boolean) as PluginConfigItem[]
      } else {
        const parsed = parseJsonField(rawConfig || '{}', { allowEmpty: false })
        if (isParseError(parsed)) {
          message.error(parsed.error)
          setSaving(false)
          return
        }
        const values = await connectionForm.validateFields()
        try {
          items = buildConnectionConfigItems({
            fields: {
              baseUrl: values.baseUrl || '',
              apiKey: values.apiKey || '',
              headersText: values.headersText || '{}',
            },
            advanced: (parsed.value || {}) as Record<string, unknown>,
            hasExistingApiKey: Boolean(hasValueRef.current.api_key),
          })
        } catch {
          message.error('附加请求头格式不正确，请填写 JSON 对象')
          return
        }
      }
      await updatePluginConfig(id, items)
      const serverConfigured = items.some((item) => item.name === 'base_url' && item.value)
      const servers = (plugin?.api_spec?.servers as Array<{ url?: string }> | undefined) || []
      setHasConnection(serverConfigured || servers.some((server) => Boolean(server.url)))
      message.success('连接信息已保存')
    } catch {
      // interceptor handles error toast
    } finally {
      setSaving(false)
    }
  }

  // ── 端点 ──────────────────────────────────────────────────────────────
  const openEpModal = (ep?: PluginEndpoint) => {
    setEditingEp(ep ?? null)
    if (ep) {
      epForm.setFieldsValue({
        endpoint: ep.endpoint,
        method: ep.method,
        description: ep.description,
      })
      setEpHeaders(ep.headers ? JSON.stringify(ep.headers, null, 2) : '')
      setEpReqSchema(
        ep.request_body_schema ? JSON.stringify(ep.request_body_schema, null, 2) : ''
      )
      setEpRespSchema(
        ep.response_schema ? JSON.stringify(ep.response_schema, null, 2) : ''
      )
    } else {
      epForm.resetFields()
      epForm.setFieldsValue({ method: 'POST' })
      setEpHeaders('')
      setEpReqSchema('')
      setEpRespSchema('')
    }
    setEpModalOpen(true)
  }

  const handleEpSubmit = async () => {
    if (!id) return
    const values = await epForm.validateFields()
    setEpSubmitting(true)
    try {
      const payload: PluginEndpointCreateRequest = {
        endpoint: values.endpoint,
        method: values.method,
        description: values.description,
        headers: null,
        request_body_schema: null,
        response_schema: null,
      }
      const jsonFields: Array<{
        key: 'headers' | 'request_body_schema' | 'response_schema'
        text: string
        label: string
      }> = [
        { key: 'headers', text: epHeaders, label: '请求头' },
        { key: 'request_body_schema', text: epReqSchema, label: '请求体 Schema' },
        { key: 'response_schema', text: epRespSchema, label: '响应 Schema' },
      ]
      for (const f of jsonFields) {
        if (f.text && f.text.trim()) {
          const parsed = parseJsonField(f.text)
          if (isParseError(parsed)) {
            message.error(`${f.label}：${parsed.error}`)
            setEpSubmitting(false)
            return
          }
          payload[f.key] = parsed.value as Record<string, unknown>
        }
      }
      if (editingEp) {
        await updateEndpoint(id, editingEp.id, payload as PluginEndpointUpdateRequest)
        message.success('端点已更新')
      } else {
        await addEndpoint(id, payload)
        message.success('端点已添加')
      }
      setEpModalOpen(false)
      const epRes = await listEndpoints(id)
      setEndpoints(epRes.data ?? [])
    } catch {
      // interceptor / validateFields
    } finally {
      setEpSubmitting(false)
    }
  }

  const handleDeleteEp = async (epId: string) => {
    if (!id) return
    try {
      await deleteEndpoint(id, epId)
      message.success('端点已删除')
      const epRes = await listEndpoints(id)
      setEndpoints(epRes.data ?? [])
    } catch {
      // interceptor
    }
  }

  const handleImportEndpoints = async () => {
    if (!id) return
    try {
      const res = await importEndpoints(id)
      message.success(res.data?.imported ? `已导入 ${res.data.imported} 个端点` : '导入完成')
      const epRes = await listEndpoints(id)
      setEndpoints(epRes.data ?? [])
    } catch {
      // interceptor
    }
  }

  // ── 测试 ──────────────────────────────────────────────────────────────
  const openTestModal = () => {
    setTestResult(null)
    testForm.resetFields()
    setTestParamsText('')
    setTestModalOpen(true)
  }

  const handleTest = async () => {
    if (!id) return
    const values = await testForm.validateFields()
    setTesting(true)
    try {
      let params: Record<string, unknown> | undefined
      if (testParamsText && testParamsText.trim()) {
        const parsed = parseJsonField(testParamsText)
        if (isParseError(parsed)) {
          message.error(`参数：${parsed.error}`)
          setTesting(false)
          return
        }
        params = parsed.value as Record<string, unknown>
      }
      const res = await testPlugin(id, {
        endpoint: values.endpoint || undefined,
        method: values.method || undefined,
        params,
      })
      setTestResult(res.data ?? null)
    } catch {
      // interceptor
    } finally {
      setTesting(false)
    }
  }

  const epColumns: ColumnsType<PluginEndpoint> = [
    {
      title: '能力',
      key: 'ability',
      render: (_, record) => (
        <Space orientation="vertical" size={2}>
          <Text strong>{record.description || '未命名能力'}</Text>
          <Text type="secondary" className="plugin-technical">
            {record.method.toUpperCase()} {record.endpoint}
          </Text>
        </Space>
      ),
    },
    {
      title: '操作',
      key: 'actions',
      render: (_, record) => (
        <Space>
          <Button size="small" icon={<EditOutlined />} onClick={() => openEpModal(record)}>
            编辑
          </Button>
          <Popconfirm title="删除这项能力？" onConfirm={() => handleDeleteEp(record.id)} okText="删除" cancelText="保留">
            <Button size="small" icon={<DeleteOutlined />} danger>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  const setupSteps = getSetupProgress({
    hasConnection,
    endpointCount: endpoints.length,
    testSucceeded: Boolean(testResult?.success),
  })

  if (loading) return null

  return (
    <div className="plugin-experience-page plugin-setup-page">
      <Button
        type="text"
        className="plugin-back-button"
        icon={<ArrowLeftOutlined />}
        onClick={() => navigate('/plugins')}
      >
        返回插件
      </Button>

      {plugin && (
        <section className="plugin-setup-hero">
          <div>
            <Text className="plugin-eyebrow">设置与试用</Text>
            <Title level={1}>让{plugin.name}开始工作</Title>
            <Text>{plugin.description || '连接服务并添加能力，完成后就可以交给 Agent 使用。'}</Text>
          </div>
          <span className={`plugin-readiness plugin-readiness--${plugin.status === 'active' ? 'ready' : 'muted'}`}>
            <span className="plugin-readiness__dot" />
            {plugin.status === 'active' ? '插件已开启' : '插件已暂停'}
          </span>
        </section>
      )}

      <nav className="plugin-setup-track" aria-label="插件设置进度">
        {setupSteps.map((step, index) => (
          <div className={`plugin-setup-step plugin-setup-step--${step.status}`} key={step.key}>
            <span className="plugin-setup-step__marker">
              {step.status === 'complete' ? <CheckOutlined /> : index + 1}
            </span>
            <span>
              <strong>{step.label}</strong>
              <small>{step.hint}</small>
            </span>
          </div>
        ))}
      </nav>

      <Card
        className="plugin-setup-card"
        title={
          <div className="plugin-card-title">
            <span className="plugin-card-title__number">1</span>
            <span><strong>连接服务</strong><small>告诉系统去哪里访问服务，以及需要使用哪些凭据</small></span>
          </div>
        }
        extra={
          <Button type="primary" icon={<SaveOutlined />} loading={saving} onClick={handleSaveConfig}>
            保存连接
          </Button>
        }
      >
        {hasSchema ? (
          <Form form={form} layout="vertical" className="plugin-connection-form">
            {Object.entries(schemaProperties).map(([name, prop]) => renderSchemaField(name, prop))}
          </Form>
        ) : (
          <Form form={connectionForm} layout="vertical" className="plugin-connection-form">
            <div className="plugin-form-grid">
              <Form.Item
                name="baseUrl"
                label="服务地址"
                extra="插件要访问的服务地址。若服务说明中已经包含地址，可以留空。"
              >
                <Input placeholder="https://api.example.com" />
              </Form.Item>
              <Form.Item
                name="apiKey"
                label="访问密钥"
                extra={hasExistingApiKey ? '已保存密钥；留空会继续使用原密钥。' : '服务无需密钥时可以留空。'}
              >
                <Password placeholder={hasExistingApiKey ? '已保存，留空不修改' : '输入访问密钥'} />
              </Form.Item>
            </div>
            <Form.Item
              name="headersText"
              label="附加请求头"
              extra="仅在服务要求额外身份信息时填写；多数情况下保持空对象即可。"
            >
              <TextArea rows={4} className="plugin-code-field" placeholder='{"X-Team":"studio"}' />
            </Form.Item>
            <Collapse
              ghost
              className="plugin-advanced-collapse"
              items={[{
                key: 'other-config',
                label: '其他连接设置',
                children: (
                  <JsonField
                    label="高级配置"
                    tooltip="用于该服务特有的连接字段。每个顶层键会保存为一个独立配置项。"
                    placeholder='{"region":"cn-east"}'
                    example='{\n  "region": "cn-east"\n}'
                    value={rawConfig}
                    onChange={setRawConfig}
                    rows={5}
                  />
                ),
              }]}
            />
          </Form>
        )}
      </Card>

      <Card
        className="plugin-setup-card"
        title={
          <div className="plugin-card-title">
            <span className="plugin-card-title__number">2</span>
            <span><strong>添加能力</strong><small>明确告诉 Agent，这个插件可以完成哪些操作</small></span>
          </div>
        }
        extra={
          <Space wrap>
            <Button icon={<ImportOutlined />} onClick={handleImportEndpoints}>从服务说明读取</Button>
            <Button icon={<PlusOutlined />} onClick={() => openEpModal()}>手动添加</Button>
            <Button type="primary" icon={<ThunderboltOutlined />} onClick={openTestModal}>试用插件</Button>
          </Space>
        }
      >
        <Table
          columns={epColumns}
          dataSource={endpoints}
          rowKey="id"
          pagination={false}
          locale={{ emptyText: '还没有可用能力。可以从服务说明读取，也可以手动添加一项。' }}
        />
      </Card>

      <section className="plugin-activation-card">
        <div>
          <Text className="plugin-eyebrow">最后一步</Text>
          <Title level={3}>把需要的能力交给 Agent</Title>
          <Text>进入 Agent 编辑页，选择这个插件中允许它使用的能力。未选择的操作不会暴露给 Agent。</Text>
        </div>
        <Button type="primary" size="large" onClick={() => navigate('/agents')}>
          去 Agent 开启使用 <ArrowRightOutlined />
        </Button>
      </section>

      {/* 端点编辑弹窗 */}
      <Modal
        title={editingEp ? '编辑能力' : '添加能力'}
        open={epModalOpen}
        onOk={handleEpSubmit}
        onCancel={() => setEpModalOpen(false)}
        confirmLoading={epSubmitting}
        okText={editingEp ? '保存能力' : '添加能力'}
        cancelText="取消"
        width={640}
        destroyOnHidden
      >
        <div className="plugin-modal-intro">
          一项能力代表 Agent 可以完成的一件事。名称要说明什么时候使用、能得到什么结果。
        </div>
        <Form form={epForm} layout="vertical">
          <Space style={{ display: 'flex' }} size="large">
            <Form.Item name="method" label="调用方式" rules={[{ required: true }]}>
              <Select options={HTTP_METHODS.map((m) => ({ value: m, label: m }))} style={{ width: 140 }} />
            </Form.Item>
            <Form.Item
              name="endpoint"
              label="服务路径"
              rules={[{ required: true }]}
              style={{ flex: 1 }}
            >
              <Input placeholder="/v1/search" />
            </Form.Item>
          </Space>
          <Form.Item name="description" label="能力名称与用途">
            <Input placeholder="例如：搜索企业资料，返回匹配的文档摘要" />
          </Form.Item>
          <Collapse
            ghost
            className="plugin-advanced-collapse"
            items={[{
              key: 'ability-advanced',
              label: '高级设置',
              children: (
                <>
                  <JsonField
                    label="固定请求头"
                    tooltip="每次使用这项能力时都会携带的请求头，会与连接信息中的请求头合并。"
                    placeholder='{"X-Api-Key":"..."}'
                    example='{\n  "X-Api-Key": "xxx",\n  "Content-Type": "application/json"\n}'
                    value={epHeaders}
                    onChange={setEpHeaders}
                    rows={2}
                  />
                  <JsonField
                    label="输入格式"
                    tooltip="用 JSON Schema 告诉 Agent 这项能力接受哪些输入。"
                    placeholder='{"type":"object","properties":{"query":{"type":"string"}},"required":["query"]}'
                    example='{\n  "type": "object",\n  "properties": {\n    "query": { "type": "string", "description": "查询内容" }\n  },\n  "required": ["query"]\n}'
                    value={epReqSchema}
                    onChange={setEpReqSchema}
                    rows={4}
                  />
                  <JsonField
                    label="返回格式"
                    tooltip="用 JSON Schema 描述服务返回的内容，可以留空。"
                    placeholder='{"type":"object","properties":{"result":{"type":"string"}}}'
                    example='{\n  "type": "object",\n  "properties": {\n    "result": { "type": "string" }\n  }\n}'
                    value={epRespSchema}
                    onChange={setEpRespSchema}
                    rows={4}
                  />
                </>
              ),
            }]}
          />
        </Form>
      </Modal>

      {/* 测试弹窗 */}
      <Modal
        title="试用插件"
        open={testModalOpen}
        onOk={handleTest}
        onCancel={() => setTestModalOpen(false)}
        confirmLoading={testing}
        okText="开始试用"
      >
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 12 }}
          title="先选择一项能力并提供示例内容，系统会立即调用真实服务。留空能力时只检查服务是否可以访问。"
        />
        <Form form={testForm} layout="vertical">
          <Form.Item
            name="endpoint"
            label="选择要试用的能力"
            tooltip="留空时仅检查服务是否可以访问。"
          >
            <Select
              allowClear
              placeholder="选择一项能力；留空只检查连接"
              options={endpoints.map((e) => ({
                value: e.endpoint,
                label: e.description ? `${e.description} · ${e.method} ${e.endpoint}` : `${e.method} ${e.endpoint}`,
              }))}
            />
          </Form.Item>
          <JsonField
            label="试用内容"
            tooltip="填写一次真实试用需要的内容，例如查询词或记录信息。"
            placeholder='{"query":"北京天气"}'
            example='{\n  "query": "北京天气"\n}'
            value={testParamsText}
            onChange={setTestParamsText}
            rows={4}
          />
          <Collapse
            ghost
            className="plugin-advanced-collapse"
            items={[{
              key: 'test-advanced',
              label: '高级设置',
              children: (
                <Form.Item name="method" label="临时覆盖调用方式">
                  <Select
                    allowClear
                    options={HTTP_METHODS.map((m) => ({ value: m, label: m }))}
                    style={{ width: 180 }}
                  />
                </Form.Item>
              ),
            }]}
          />
        </Form>
        {testResult && (
          <Space orientation="vertical" style={{ width: '100%' }}>
            <Badge
              status={testResult.success ? 'success' : 'error'}
              text={testResult.success ? '调用成功' : '调用失败'}
            />
            <div>状态码：{testResult.status_code ?? '—'}</div>
            <div>耗时：{testResult.latency_ms ?? '—'} ms</div>
            {testResult.error && <Text type="danger">错误：{testResult.error}</Text>}
            <TextArea
              readOnly
              rows={6}
              value={
                typeof testResult.data === 'string'
                  ? testResult.data
                  : JSON.stringify(testResult.data, null, 2)
              }
            />
          </Space>
        )}
      </Modal>
    </div>
  )
}
