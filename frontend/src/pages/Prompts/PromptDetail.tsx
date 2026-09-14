import { useCallback, useEffect, useRef, useState } from 'react'
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
import { ArrowLeftOutlined, EditOutlined, PlayCircleOutlined, CheckOutlined } from '@ant-design/icons'
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
  const promptId = id || ''
  const navigate = useNavigate()

  const [prompt, setPrompt] = useState<Prompt | null>(null)
  const [versions, setVersions] = useState<PromptVersion[]>([])
  const [selectedVersion, setSelectedVersion] = useState<PromptVersion | null>(null)
  const [models, setModels] = useState<AIModel[]>([])
  const [testResult, setTestResult] = useState<PromptTestResult | null>(null)
  const [testing, setTesting] = useState(false)
  const [form] = Form.useForm()
  /** 「版本内容」预览区的引用，供「查看」后滚动定位。 */
  const previewRef = useRef<HTMLDivElement | null>(null)

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

  const handleActivate = async (versionId: string) => {
    try {
      await activateVersion(promptId, versionId)
      message.success('版本已激活')
      load()
    } catch {
      // interceptor handles error toast
    }
  }

  /** 该版本是否即当前正在预览的版本。 */
  const isPreviewing = (r: PromptVersion) => selectedVersion?.id === r.id

  /**
   * 选中某版本用于预览（直接点击版本行触发）。
   *
   * 这里刻意不设「查看」按钮：预览区本就常驻、且默认显示当前版本，再放一个按钮
   * 只是把已经可见的内容再换一次；当 prompt 只有一个版本时，点击必然零变化，
   * 反而会被误认为按钮失效。改为「选中行即预览」后，选中态只需由行底色表达，
   * 下方卡片标题已写明是哪一版，无需再叠标签。
   */
  const handleSelectVersion = (version: PromptVersion) => {
    if (!isPreviewing(version)) setSelectedVersion(version)
    requestAnimationFrame(() => {
      previewRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
    })
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
  ]

  // 「操作」列只在确实存在可操作的历史版本时才渲染。
  // 只有一个版本时，这一列每行都没有内容，白占一列表头，属于噪声。
  if (versions.some((v) => !v.is_current)) {
    versionColumns.push({
      title: '操作',
      key: 'actions',
      width: 96,
      render: (_, r) =>
        r.is_current ? null : (
          <Button
            size="small"
            icon={<CheckOutlined />}
            onClick={(e) => {
              // 行本身可点击（选中预览），阻止冒泡以免顺带改变预览目标。
              e.stopPropagation()
              handleActivate(r.id)
            }}
          >
            激活
          </Button>
        ),
    })
  }

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
        <Space>
          {/* 显式回列表：不依赖浏览器历史，避免从编辑页保存后无法回到列表 */}
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/prompts')}>
            返回列表
          </Button>
          <Button
            icon={<EditOutlined />}
            onClick={() => navigate(`/prompts/${promptId}/edit`)}
          >
            编辑
          </Button>
        </Space>
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
              onRow={(r) => ({
                onClick: () => handleSelectVersion(r),
                style: {
                  cursor: 'pointer',
                  ...(isPreviewing(r) ? { background: '#e6f4ff' } : {}),
                },
              })}
            />
            <Text type="secondary" style={{ fontSize: 12 }}>
              点击版本行可在下方查看该版本内容
            </Text>
          </Card>

          {/* Selected version content preview */}
          <div ref={previewRef}>
            {selectedVersion && (
              <Card
                title={
                  <Space>
                    <span>{`版本内容 — v${selectedVersion.version_number}`}</span>
                    {selectedVersion.is_current && <Tag color="green">当前版本</Tag>}
                  </Space>
                }
                size="small"
              >
                <CodeEditor value={selectedVersion.content} readOnly height={300} />
              </Card>
            )}
          </div>
        </Col>

        <Col span={10}>
          {/* Test run panel */}
          <Card title={<Space><PlayCircleOutlined />测试运行</Space>} size="small">
            {/* 测试目标＝上方选中的版本，这里显式标出，避免「点行换预览」后
                测试对象在无感知的情况下被改变。 */}
            <Text type="secondary">
              {selectedVersion
                ? `测试版本：v${selectedVersion.version_number}`
                : '暂无可测试的版本'}
            </Text>
            <Form form={form} layout="vertical" style={{ marginTop: 12 }}>
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
              {testing && (
                <Text type="secondary" style={{ display: 'block', marginTop: 8 }}>
                  模型推理进行中，可能需要数十秒（本地模型首次调用更久），请勿关闭页面。
                </Text>
              )}
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
