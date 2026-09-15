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
  Tag,
  Table,
  Modal,
  message,
  Descriptions,
  Badge,
  Popconfirm,
  Alert,
  Tooltip,
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
import { pluginSourceMeta } from './pluginMeta'

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

  const [hasSchema, setHasSchema] = useState(false)
  const [rawConfig, setRawConfig] = useState('{}')

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
    setLoading(true)
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

      const schema = (p.config_schema as Record<string, unknown>) || null
      if (schema && (schema.properties as Record<string, unknown>)) {
        setHasSchema(true)
        form.setFieldsValue(cfgMap)
      } else {
        setHasSchema(false)
        setRawConfig(JSON.stringify(cfgMap, null, 2))
      }

      const epRes = await listEndpoints(id)
      setEndpoints(epRes.data ?? [])
    } catch {
      // interceptor handles error toast
    } finally {
      setLoading(false)
    }
  }, [id, form])

  useEffect(() => {
    load()
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
        const obj = parsed.value as Record<string, unknown>
        // 裸 JSON 模式：剥离 null 与脱敏占位 "********"，避免覆盖已设置的敏感项
        items = Object.entries(obj)
          .filter(([, v]) => v !== null && v !== '********')
          .map(([name, value]) => ({ name, value }))
      }
      await updatePluginConfig(id, items)
      message.success('配置已保存')
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
      title: '方法',
      dataIndex: 'method',
      key: 'method',
      render: (m) => <Tag color="blue">{m}</Tag>,
    },
    { title: '端点', dataIndex: 'endpoint', key: 'endpoint', render: (e) => <code>{e}</code> },
    {
      title: '描述',
      dataIndex: 'description',
      key: 'description',
      render: (d) => d || '—',
    },
    {
      title: '操作',
      key: 'actions',
      render: (_, record) => (
        <Space>
          <Button size="small" icon={<EditOutlined />} onClick={() => openEpModal(record)} />
          <Popconfirm title="确认删除此端点？" onConfirm={() => handleDeleteEp(record.id)} okText="删除" cancelText="取消">
            <Button size="small" icon={<DeleteOutlined />} danger />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  const sourceMeta = pluginSourceMeta(plugin?.source_type)

  if (loading) return null

  return (
    <div>
      <Space style={{ marginBottom: 16 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/plugins')}>
          返回
        </Button>
        <Title level={4} style={{ margin: 0 }}>
          插件配置
        </Title>
      </Space>

      {plugin && (
        <Card style={{ marginBottom: 16 }}>
          <Descriptions column={2} size="small">
            <Descriptions.Item label="名称">{plugin.name}</Descriptions.Item>
            <Descriptions.Item label="接入方式">
              <Tooltip title={`${sourceMeta.description} 适用：${sourceMeta.useCases}`}>
                <Tag color={sourceMeta.color}>{sourceMeta.label}</Tag>
              </Tooltip>
            </Descriptions.Item>
            <Descriptions.Item label="版本">{plugin.version}</Descriptions.Item>
            <Descriptions.Item label="状态">
              <Badge
                status={plugin.status === 'active' ? 'success' : 'default'}
                text={plugin.status}
              />
            </Descriptions.Item>
            <Descriptions.Item label="作者">{plugin.author || '—'}</Descriptions.Item>
            <Descriptions.Item label="可见性">
              {plugin.is_public ? '公共插件' : '租户私有'}
            </Descriptions.Item>
            {plugin.description && (
              <Descriptions.Item label="描述" span={2}>
                {plugin.description}
              </Descriptions.Item>
            )}
          </Descriptions>
        </Card>
      )}

      {/* 配置表单 */}
      <Card
        title="连接与凭据配置"
        extra={
          <Button
            type="primary"
            icon={<SaveOutlined />}
            loading={saving}
            onClick={handleSaveConfig}
          >
            保存配置
          </Button>
        }
        style={{ marginBottom: 16 }}
      >
        {hasSchema ? (
          <Form form={form} layout="vertical">
            {Object.entries(schemaProperties).map(([name, prop]) =>
              renderSchemaField(name, prop)
            )}
          </Form>
        ) : (
          <Space direction="vertical" style={{ width: '100%' }}>
            <Alert
              type="info"
              showIcon
              style={{ width: '100%' }}
              message="填写你的组织接入该插件所需的连接与凭据"
              description={
                <div>
                  <div>
                    这是<strong>当前组织（租户）使用该插件</strong>所需的地址与密钥，仅对本组织生效，与其他租户互不干扰。该插件未定义表单 Schema，请以 JSON 对象形式填写，每个顶层键对应一个配置项。
                  </div>
                  <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>
                    <li>
                      <code>base_url</code>（<strong>必填</strong>）：插件后端服务的基址，例如{' '}
                      <code>https://api.example.com</code>。测试连通性、调用端点都依赖它。
                    </li>
                    <li>
                      <code>api_key</code>（可选）：鉴权密钥，会自动以 Bearer 方式注入请求头；如需自定义头名可配 <code>api_key_header</code>。
                    </li>
                    <li>
                      <code>headers</code>（可选）：额外的默认请求头，例如{' '}
                      <code>{'{"X-Tenant-Id":"abc"}'}</code>。
                    </li>
                  </ul>
                </div>
              }
            />
            <TextArea
              rows={8}
              value={rawConfig}
              onChange={(e) => setRawConfig(e.target.value)}
              placeholder={`{\n  "base_url": "https://api.example.com",\n  "api_key": "...",\n  "headers": { "X-Tenant-Id": "abc" }\n}`}
              status={
                (() => {
                  const parsed = parseJsonField(rawConfig || '{}', { allowEmpty: false })
                  return parsed.ok ? '' : 'error'
                })()
              }
            />
            {(() => {
              const parsed = parseJsonField(rawConfig || '{}', { allowEmpty: false })
              if (parsed.ok && parsed.value && typeof parsed.value === 'object') {
                const keys = Object.keys(parsed.value as Record<string, unknown>)
                if (keys.length > 0 && !keys.includes('base_url')) {
                  return (
                    <Alert
                      type="warning"
                      showIcon
                      style={{ width: '100%' }}
                      message="建议配置 base_url"
                      description="当前配置缺少 base_url，测试连通性（不选择端点时）将无法进行。请补充 base_url 指向插件后端服务地址。"
                    />
                  )
                }
              }
              return null
            })()}
          </Space>
        )}
      </Card>

      {/* 端点管理 */}
      <Card
        title="插件端点"
        extra={
          <Space>
            <Button icon={<ImportOutlined />} onClick={handleImportEndpoints}>
              从 OpenAPI 导入
            </Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => openEpModal()}>
              新增端点
            </Button>
            <Button icon={<ThunderboltOutlined />} onClick={openTestModal}>
              测试
            </Button>
          </Space>
        }
      >
        <Table
          columns={epColumns}
          dataSource={endpoints}
          rowKey="id"
          pagination={false}
          locale={{ emptyText: '暂无端点，可手动新增或从 OpenAPI 导入' }}
        />
      </Card>

      {/* 端点编辑弹窗 */}
      <Modal
        title={editingEp ? '编辑端点' : '新增端点'}
        open={epModalOpen}
        onOk={handleEpSubmit}
        onCancel={() => setEpModalOpen(false)}
        confirmLoading={epSubmitting}
        width={640}
        destroyOnClose
      >
        <Form form={epForm} layout="vertical">
          <Space style={{ display: 'flex' }} size="large">
            <Form.Item name="method" label="方法" rules={[{ required: true }]}>
              <Select options={HTTP_METHODS.map((m) => ({ value: m, label: m }))} style={{ width: 140 }} />
            </Form.Item>
            <Form.Item
              name="endpoint"
              label="端点路径"
              rules={[{ required: true }]}
              style={{ flex: 1 }}
            >
              <Input placeholder="/v1/search" />
            </Form.Item>
          </Space>
          <Form.Item name="description" label="描述">
            <Input placeholder="对该端点的简要说明，例如：网页搜索" />
          </Form.Item>
          <JsonField
            label="请求头"
            tooltip="调用该端点时默认携带的请求头，会与服务配置中的 headers / api_key 合并。标准 JSON 对象。"
            placeholder='{"X-Api-Key":"..."}'
            example='{\n  "X-Api-Key": "xxx",\n  "Content-Type": "application/json"\n}'
            value={epHeaders}
            onChange={setEpHeaders}
            rows={2}
          />
          <JsonField
            label="请求体 Schema"
            tooltip="描述该端点请求体的 JSON Schema（不是 function-calling 描述）。用于约定调用参数结构，可留空。"
            placeholder='{"type":"object","properties":{"query":{"type":"string"}},"required":["query"]}'
            example='{\n  "type": "object",\n  "properties": {\n    "query": { "type": "string", "description": "查询内容" }\n  },\n  "required": ["query"]\n}'
            value={epReqSchema}
            onChange={setEpReqSchema}
            rows={4}
          />
          <JsonField
            label="响应 Schema"
            tooltip="描述该端点返回结构的 JSON Schema，可选。"
            placeholder='{"type":"object","properties":{"result":{"type":"string"}}}'
            example='{\n  "type": "object",\n  "properties": {\n    "result": { "type": "string" }\n  }\n}'
            value={epRespSchema}
            onChange={setEpRespSchema}
            rows={4}
          />
        </Form>
      </Modal>

      {/* 测试弹窗 */}
      <Modal
        title="测试插件"
        open={testModalOpen}
        onOk={handleTest}
        onCancel={() => setTestModalOpen(false)}
        confirmLoading={testing}
        okText="运行测试"
      >
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 12 }}
          message="两种测试模式"
          description={
            <div>
              <div>
                <strong>选择端点</strong>：按下方参数真实调用该端点（POST/PUT 等会作为请求体发送）。
              </div>
              <div style={{ marginTop: 4 }}>
                <strong>不选端点</strong>：仅探测服务连通性，需要先在上方「连接与凭据配置」中填写 <code>base_url</code>
                （或插件 OpenAPI 的 <code>servers</code>）。否则会提示「未配置服务地址」。
              </div>
            </div>
          }
        />
        <Form form={testForm} layout="vertical">
          <Form.Item
            name="endpoint"
            label="端点路径"
            tooltip="留空则进行服务连通性探测；需已在上方「连接与凭据配置」中填写 base_url。"
          >
            <Select
              allowClear
              placeholder="留空 = 探测连通性"
              options={endpoints.map((e) => ({ value: e.endpoint, label: `${e.method} ${e.endpoint}` }))}
            />
          </Form.Item>
          <Form.Item name="method" label="方法（覆盖端点默认方法）">
            <Select
              allowClear
              options={HTTP_METHODS.map((m) => ({ value: m, label: m }))}
              style={{ width: 160 }}
            />
          </Form.Item>
          <JsonField
            label="调用参数"
            tooltip="调用参数。选择端点且为非 GET 方法时作为请求体；含 {id} 形式的键会替换路径参数。"
            placeholder='{"query":"北京天气"}'
            example='{\n  "query": "北京天气"\n}'
            value={testParamsText}
            onChange={setTestParamsText}
            rows={4}
          />
        </Form>
        {testResult && (
          <Space direction="vertical" style={{ width: '100%' }}>
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
