import { useEffect, useState } from 'react'
import {
  Form,
  Input,
  Select,
  InputNumber,
  Switch,
  Button,
  Card,
  Typography,
  Space,
  message,
} from 'antd'
import { useNavigate, useParams } from 'react-router-dom'
import { createModel, getModel, updateModel, listProviders } from '@/api/ai-model'
import type { AIModelCreateRequest, AIProvider } from '@/types/ai-model'

const { Title } = Typography

const MODEL_TYPE_OPTIONS = [
  { value: 'chat', label: '对话（Chat）' },
  { value: 'embedding', label: 'Embedding' },
  { value: 'image', label: '图像生成' },
  { value: 'audio', label: '音频' },
  { value: 'rerank', label: 'Rerank' },
]

export default function ModelForm() {
  const navigate = useNavigate()
  const { id } = useParams<{ id: string }>()
  const isEdit = Boolean(id)
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [providers, setProviders] = useState<AIProvider[]>([])
  const [initializing, setInitializing] = useState(true)

  useEffect(() => {
    const init = async () => {
      try {
        const providersRes = await listProviders({ page: 1, page_size: 100 })
        setProviders(providersRes.data?.items ?? [])
        if (isEdit && id) {
          const modelRes = await getModel(Number(id))
          const m = modelRes.data
          form.setFieldsValue({
            provider_id: m.provider_id,
            name: m.name,
            display_name: m.display_name,
            model_type: m.model_type,
            unit_price_input: m.unit_price_input,
            unit_price_output: m.unit_price_output,
            max_context_tokens: m.max_context_tokens,
            max_output_tokens: m.max_output_tokens,
            status: m.status,
          })
        }
      } catch {
        message.error('初始化失败')
      } finally {
        setInitializing(false)
      }
    }
    init()
  }, [id, isEdit, form])

  const handleSubmit = async (values: Record<string, unknown>) => {
    setLoading(true)
    try {
      const payload: AIModelCreateRequest = {
        provider_id: values.provider_id as number,
        name: values.name as string,
        display_name: values.display_name as string,
        model_type: values.model_type as AIModelCreateRequest['model_type'],
        status: values.status as boolean,
        unit_price_input: values.unit_price_input as string | undefined,
        unit_price_output: values.unit_price_output as string | undefined,
        max_context_tokens: values.max_context_tokens as number | undefined,
        max_output_tokens: values.max_output_tokens as number | undefined,
      }
      if (isEdit && id) {
        await updateModel(Number(id), payload)
        message.success('更新成功')
      } else {
        await createModel(payload)
        message.success('创建成功')
      }
      navigate('/ai-models')
    } catch (e: unknown) {
      const err = e as { response?: { data?: { message?: string } } }
      message.error(err?.response?.data?.message || (isEdit ? '更新失败' : '创建失败'))
    } finally {
      setLoading(false)
    }
  }

  if (initializing) return null

  return (
    <div style={{ maxWidth: 640, margin: '0 auto' }}>
      <Title level={4}>{isEdit ? '编辑模型' : '新增模型'}</Title>
      <Card>
        <Form form={form} layout="vertical" onFinish={handleSubmit} initialValues={{ status: true }}>
          <Form.Item name="provider_id" label="所属供应商" rules={[{ required: true }]}>
            <Select
              placeholder="选择供应商"
              options={providers.map((p) => ({ value: p.id, label: p.name }))}
            />
          </Form.Item>

          <Form.Item name="name" label="模型标识" rules={[{ required: true }]}
            extra="如：gpt-4o、claude-3-5-sonnet-20241022">
            <Input placeholder="模型的 API 调用名称" />
          </Form.Item>

          <Form.Item name="display_name" label="显示名称" rules={[{ required: true }]}>
            <Input placeholder="如：GPT-4o" />
          </Form.Item>

          <Form.Item name="model_type" label="模型类型" rules={[{ required: true }]}>
            <Select options={MODEL_TYPE_OPTIONS} />
          </Form.Item>

          <Form.Item name="unit_price_input" label="输入单价（$/1K tokens）">
            <InputNumber style={{ width: '100%' }} min={0} step={0.000001} placeholder="0.000005" />
          </Form.Item>

          <Form.Item name="unit_price_output" label="输出单价（$/1K tokens）">
            <InputNumber style={{ width: '100%' }} min={0} step={0.000001} placeholder="0.000015" />
          </Form.Item>

          <Form.Item name="max_context_tokens" label="最大上下文 Token">
            <InputNumber style={{ width: '100%' }} min={1} placeholder="128000" />
          </Form.Item>

          <Form.Item name="max_output_tokens" label="最大输出 Token">
            <InputNumber style={{ width: '100%' }} min={1} placeholder="4096" />
          </Form.Item>

          <Form.Item name="status" label="启用状态" valuePropName="checked">
            <Switch checkedChildren="启用" unCheckedChildren="禁用" />
          </Form.Item>

          <Form.Item>
            <Space>
              <Button type="primary" htmlType="submit" loading={loading}>
                {isEdit ? '保存修改' : '创建模型'}
              </Button>
              <Button onClick={() => navigate('/ai-models')}>取消</Button>
            </Space>
          </Form.Item>
        </Form>
      </Card>
    </div>
  )
}
