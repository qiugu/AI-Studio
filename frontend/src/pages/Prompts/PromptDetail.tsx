import { useCallback, useEffect, useState } from 'react'
import {
  Button,
  Space,
  Typography,
  Card,
  Tag,
  Table,
  Form,
  Input,
  Select,
  Divider,
  message,
  Spin,
  Row,
  Col,
  Badge,
} from 'antd'
import { EditOutlined, PlayCircleOutlined, CheckOutlined } from '@ant-design/icons'
import { useNavigate, useParams } from 'react-router-dom'
import type { ColumnsType } from 'antd/es/table'
import CodeEditor from '@/components/CodeEditor'
import { getPrompt, listVersions, activateVersion, testPrompt } from '@/api/prompt'
import { listModels } from '@/api/ai-model'
import type { Prompt, PromptVersion, PromptTestResult } from '@/types/prompt'
import type { AIModel } from '@/types/ai-model'

const { Title, Text } = Typography

export default function PromptDetail() {
  const { id } = useParams<{ id: string }>()
  const promptId = Number(id)
  const navigate = useNavigate()

  const [prompt, setPrompt] = useState<Prompt | null>(null)
  const [versions, setVersions] = useState<PromptVersion[]>([])
  const [selectedVersion, setSelectedVersion] = useState<PromptVersion | null>(null)
  const [models, setModels] = useState<AIModel[]>([])
  const [testResult, setTestResult] = useState<PromptTestResult | null>(null)
  const [testing, setTesting] = useState(false)
  const [form] = Form.useForm()

  const load = useCallback(async () => {
    const [pRes, vRes, mRes] = await Promise.all([
      getPrompt(promptId),
      listVersions(promptId),
      listModels({ page: 1, page_size: 100, model_type: 'chat' }),
    ])
    const p = pRes.data!
    setPrompt(p)
    setVersions(vRes.data ?? [])
    setModels(mRes.data?.items ?? [])
    const current = (vRes.data ?? []).find((v) => v.is_current) ?? (vRes.data ?? [])[0] ?? null
    setSelectedVersion(current)
  }, [promptId])

  useEffect(() => {
    load()
  }, [load])

  const handleActivate = async (versionId: number) => {
    try {
      await activateVersion(promptId, versionId)
      message.success('版本已激活')
      load()
    } catch {
      // interceptor handles error toast
    }
  }

  const handleTest = async () => {
    const values = await form.validateFields()
    const vars: Record<string, string> = {}
    const varNames = selectedVersion?.variables ?? []
    varNames.forEach((v) => { vars[v] = values[`var_${v}`] ?? '' })
    setTesting(true)
    setTestResult(null)
    try {
      const res = await testPrompt(promptId, {
        version_id: selectedVersion?.id,
        variables: vars,
        model_id: values.model_id,
      })
      setTestResult(res.data!)
    } catch {
      // interceptor handles error toast
    } finally {
      setTesting(false)
    }
  }

  const versionColumns: ColumnsType<PromptVersion> = [
    {
      title: '版本',
      key: 'v',
      render: (_, r) => (
        <Space>
          <span>{`v${r.version_number}`}</span>
          {r.is_current && <Tag color="green">当前</Tag>}
        </Space>
      ),
    },
    {
      title: '变量',
      key: 'vars',
      render: (_, r) => r.variables?.map((v) => <Tag key={v} color="blue">{`{{${v}}}`}</Tag>) ?? '—',
    },
    { title: '创建时间', dataIndex: 'created_at', key: 'created_at', render: (v) => v?.slice(0, 16) ?? '—' },
    {
      title: '操作',
      key: 'actions',
      render: (_, r) => (
        <Space>
          <Button size="small" onClick={() => setSelectedVersion(r)}>查看</Button>
          {!r.is_current && (
            <Button
              size="small"
              icon={<CheckOutlined />}
              onClick={() => handleActivate(r.id)}
            >
              激活
            </Button>
          )}
        </Space>
      ),
    },
  ]

  if (!prompt) return <Spin />

  const varNames = selectedVersion?.variables ?? []

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <Space>
          <Title level={4} style={{ margin: 0 }}>{prompt.name}</Title>
          <Badge
            status={prompt.status === 'published' ? 'success' : prompt.status === 'archived' ? 'warning' : 'default'}
            text={prompt.status === 'published' ? '已发布' : prompt.status === 'archived' ? '已归档' : '草稿'}
          />
        </Space>
        <Button
          icon={<EditOutlined />}
          onClick={() => navigate(`/prompts/${promptId}/edit`)}
        >
          编辑
        </Button>
      </div>

      <Row gutter={16}>
        <Col span={14}>
          {/* Version history */}
          <Card title="版本历史" size="small" style={{ marginBottom: 16 }}>
            <Table
              columns={versionColumns}
              dataSource={versions}
              rowKey="id"
              size="small"
              pagination={false}
            />
          </Card>

          {/* Selected version content preview */}
          {selectedVersion && (
            <Card
              title={`版本内容 — v${selectedVersion.version_number}`}
              size="small"
            >
              <CodeEditor value={selectedVersion.content} readOnly height={300} />
            </Card>
          )}
        </Col>

        <Col span={10}>
          {/* Test run panel */}
          <Card title={<Space><PlayCircleOutlined />测试运行</Space>} size="small">
            <Form form={form} layout="vertical">
              <Form.Item
                name="model_id"
                label="选择模型"
                rules={[{ required: true, message: '请选择模型' }]}
              >
                <Select
                  placeholder="选择 Chat 模型"
                  options={models.map((m) => ({ value: m.id, label: m.display_name }))}
                />
              </Form.Item>

              {varNames.length > 0 && (
                <>
                  <Divider plain>变量值</Divider>
                  {varNames.map((v) => (
                    <Form.Item
                      key={v}
                      name={`var_${v}`}
                      label={`{{${v}}}`}
                    >
                      <Input placeholder={`输入 ${v} 的值`} />
                    </Form.Item>
                  ))}
                </>
              )}

              <Button
                type="primary"
                block
                icon={<PlayCircleOutlined />}
                loading={testing}
                onClick={handleTest}
              >
                运行测试
              </Button>
            </Form>

            {testResult && (
              <>
                <Divider />
                <div style={{ marginBottom: 8 }}>
                  <Text type="secondary">
                    {`Tokens: ${testResult.prompt_tokens} + ${testResult.completion_tokens} | 耗时: ${testResult.latency_ms}ms`}
                  </Text>
                </div>
                <Card size="small" title="渲染后内容" style={{ marginBottom: 8 }}>
                  <pre style={{ whiteSpace: 'pre-wrap', margin: 0, fontSize: 12 }}>
                    {testResult.rendered_content}
                  </pre>
                </Card>
                <Card size="small" title="模型返回">
                  <pre style={{ whiteSpace: 'pre-wrap', margin: 0, fontSize: 12 }}>
                    {testResult.result_content}
                  </pre>
                </Card>
              </>
            )}
          </Card>
        </Col>
      </Row>
    </div>
  )
}
