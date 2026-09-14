import { useEffect, useState } from 'react'
import {
  Form,
  Input,
  Select,
  Button,
  Space,
  Typography,
  Card,
  Tag,
  message,
  Row,
  Col,
} from 'antd'
import { useNavigate, useParams } from 'react-router-dom'
import CodeEditor from '@/components/CodeEditor'
import { createPrompt, getPrompt, updatePrompt, createVersion, activateVersion } from '@/api/prompt'
import { executePromptSave } from './promptSave'
import type { Prompt } from '@/types/prompt'

const { Title, Text } = Typography

/** Extract {{variable}} names from content */
function extractVars(content: string): string[] {
  const matches = content.match(/\{\{(\w+)\}\}/g) ?? []
  return [...new Set(matches.map((m) => m.slice(2, -2)))]
}

export default function PromptEditor() {
  const { id } = useParams<{ id: string }>()
  const isEdit = Boolean(id)
  const navigate = useNavigate()
  const [form] = Form.useForm()
  const [content, setContent] = useState('')
  const [variables, setVariables] = useState<string[]>([])
  const [loading, setLoading] = useState(false)
  const [prompt, setPrompt] = useState<Prompt | null>(null)
  // 内容是否与当前版本不同：决定保存时是否生成新版本
  const contentChanged = prompt?.current_version?.content !== content

  useEffect(() => {
    if (isEdit && id) {
      getPrompt(id || '').then((res) => {
        const p = res.data!
        setPrompt(p)
        form.setFieldsValue({
          name: p.name,
          description: p.description,
          category: p.category,
          tags: p.tags,
          status: p.status,
        })
        const c = p.current_version?.content ?? ''
        setContent(c)
        setVariables(extractVars(c))
      })
    }
  }, [id, isEdit, form])

  const handleContentChange = (val: string) => {
    setContent(val)
    setVariables(extractVars(val))
  }

  const handleSubmit = async () => {
    const values = await form.validateFields()
    setLoading(true)
    try {
      if (!isEdit) {
        const res = await createPrompt({ ...values, content })
        message.success('Prompt 创建成功')
        // replace：用详情页替换编辑页的历史记录，使浏览器后退可直达列表页
        navigate(`/prompts/${res.data!.id}`, { replace: true })
        return
      }

      const result = await executePromptSave({
        promptId: id || '',
        isEdit: true,
        contentChanged,
        metadata: {
          name: values.name,
          description: values.description,
          category: values.category,
          tags: values.tags,
          status: values.status,
        },
        content,
        deps: { updatePrompt, createVersion, activateVersion },
      })

      // isEdit=true 时不会 skip；此分支仅作防御
      if (result.skip) return

      message.success(result.message)
      // replace：保存后编辑页不应留在历史栈中，否则后退会回到编辑页
      navigate(`/prompts/${id}`, { replace: true })
    } catch {
      // interceptor handles error toast
    } finally {
      setLoading(false)
    }
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>
          {isEdit ? '编辑 Prompt' : '新建 Prompt'}
        </Title>
        <Space>
          <Button onClick={() => navigate(-1)}>取消</Button>
          <Button type="primary" loading={loading} onClick={handleSubmit}>
            {isEdit ? '保存' : '创建'}
          </Button>
        </Space>
      </div>

      {isEdit && prompt && (
        <Card size="small" style={{ marginBottom: 16 }}>
          <Space size={12}>
            <Text type="secondary">当前版本：</Text>
            <Tag color="blue">{`v${prompt?.current_version?.version_number ?? '-'}`}</Tag>
            {contentChanged && <Text type="warning">内容已修改，保存后将自动生成新版本</Text>}
          </Space>
        </Card>
      )}

      <Row gutter={16}>
        {/* Left: variables panel */}
        <Col span={5}>
          <Card title="变量列表" size="small" style={{ minHeight: 500 }}>
            {variables.length === 0 ? (
              <Text type="secondary">在内容中使用 {'{{变量名}}'} 语法添加变量</Text>
            ) : (
              <Space direction="vertical" style={{ width: '100%' }}>
                {variables.map((v) => (
                  <Tag color="blue" key={v}>{`{{${v}}}`}</Tag>
                ))}
              </Space>
            )}
          </Card>
        </Col>

        {/* Right: editor + meta form */}
        <Col span={19}>
          <Card title="Prompt 内容" size="small" style={{ marginBottom: 16 }}>
            <CodeEditor value={content} onChange={handleContentChange} height={360} />
          </Card>

          <Card title="基本信息" size="small">
            <Form form={form} layout="vertical">
              <Row gutter={16}>
                <Col span={12}>
                  <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}>
                    <Input placeholder="例：客服欢迎语" />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item name="category" label="分类">
                    <Select
                      allowClear
                      placeholder="选择分类"
                      options={[
                        { value: 'system', label: '系统提示' },
                        { value: 'user', label: '用户指令' },
                        { value: 'few-shot', label: 'Few-shot' },
                        { value: 'chain', label: '链式调用' },
                      ]}
                    />
                  </Form.Item>
                </Col>
              </Row>
              <Form.Item name="description" label="描述">
                <Input.TextArea rows={2} placeholder="可选描述" />
              </Form.Item>
              <Row gutter={16}>
                <Col span={12}>
                  <Form.Item name="tags" label="标签">
                    <Select mode="tags" placeholder="输入后回车添加" />
                  </Form.Item>
                </Col>
                {isEdit && (
                  <Col span={12}>
                    <Form.Item name="status" label="状态">
                      <Select
                        options={[
                          { value: 'draft', label: '草稿' },
                          { value: 'published', label: '已发布' },
                          { value: 'archived', label: '已归档' },
                        ]}
                      />
                    </Form.Item>
                  </Col>
                )}
              </Row>
            </Form>
          </Card>
        </Col>
      </Row>
    </div>
  )
}
