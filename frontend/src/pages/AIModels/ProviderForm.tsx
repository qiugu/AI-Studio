import { useEffect, useState } from 'react'
import {
  Form,
  Input,
  Select,
  Switch,
  Button,
  Card,
  Typography,
  Space,
  message,
} from 'antd'
import { useNavigate, useParams } from 'react-router-dom'
import { createProvider, getProvider, updateProvider } from '@/api/ai-model'
import type { AIProviderCreateRequest } from '@/types/ai-model'

const { Title } = Typography

const PROVIDER_TYPES = [
  { value: 'openai', label: 'OpenAI' },
  { value: 'anthropic', label: 'Anthropic' },
  { value: 'azure', label: 'Azure OpenAI' },
  { value: 'zhipu', label: '智谱 AI' },
  { value: 'baichuan', label: '百川 AI' },
  { value: 'ollama', label: 'Ollama（本地）' },
  { value: 'custom', label: '自定义（OpenAI 兼容）' },
]

export default function ProviderForm() {
  const navigate = useNavigate()
  const { id } = useParams<{ id: string }>()
  const isEdit = Boolean(id)
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [initializing, setInitializing] = useState(isEdit)

  useEffect(() => {
    if (!isEdit || !id) return
    getProvider(Number(id))
      .then((res) => {
        const p = res.data
        form.setFieldsValue({
          name: p.name,
          provider_type: p.provider_type,
          api_base_url: p.api_base_url,
          config: p.config ? JSON.stringify(p.config, null, 2) : '',
          status: p.status,
        })
      })
      .catch(() => message.error('加载供应商信息失败'))
      .finally(() => setInitializing(false))
  }, [id, isEdit, form])

  const handleSubmit = async (values: Record<string, unknown>) => {
    setLoading(true)
    try {
      const payload: AIProviderCreateRequest = {
        name: values.name as string,
        provider_type: values.provider_type as AIProviderCreateRequest['provider_type'],
        api_base_url: values.api_base_url as string | undefined,
        api_key: values.api_key as string | undefined,
        status: values.status as boolean,
      }
      if (values.config) {
        try {
          payload.config = JSON.parse(values.config as string)
        } catch {
          message.error('额外配置 JSON 格式错误')
          return
        }
      }

      if (isEdit && id) {
        await updateProvider(Number(id), payload)
        message.success('更新成功')
      } else {
        await createProvider(payload)
        message.success('创建成功')
      }
      navigate('/providers')
    } catch {
      // interceptor handles error toast
    } finally {
      setLoading(false)
    }
  }

  if (initializing) return null

  return (
    <div style={{ maxWidth: 640, margin: '0 auto' }}>
      <Title level={4}>{isEdit ? '编辑供应商' : '新增供应商'}</Title>
      <Card>
        <Form form={form} layout="vertical" onFinish={handleSubmit} initialValues={{ status: true }}>
          <Form.Item name="name" label="供应商名称" rules={[{ required: true }]}>
            <Input placeholder="如：我的 OpenAI" />
          </Form.Item>

          <Form.Item name="provider_type" label="供应商类型" rules={[{ required: true }]}>
            <Select options={PROVIDER_TYPES} placeholder="选择供应商类型" />
          </Form.Item>

          <Form.Item name="api_base_url" label="API Base URL">
            <Input placeholder="如：https://api.openai.com/v1（留空使用默认）" />
          </Form.Item>

          <Form.Item
            name="api_key"
            label={isEdit ? 'API Key（留空保持不变）' : 'API Key'}
            rules={isEdit ? [] : [{ required: true, message: '请输入 API Key' }]}
          >
            <Input.Password placeholder="sk-..." />
          </Form.Item>

          <Form.Item name="config" label="额外配置（JSON 格式，可选）">
            <Input.TextArea rows={3} placeholder='{"timeout": 30}' />
          </Form.Item>

          <Form.Item name="status" label="启用状态" valuePropName="checked">
            <Switch checkedChildren="启用" unCheckedChildren="禁用" />
          </Form.Item>

          <Form.Item>
            <Space>
              <Button type="primary" htmlType="submit" loading={loading}>
                {isEdit ? '保存修改' : '创建供应商'}
              </Button>
              <Button onClick={() => navigate('/providers')}>取消</Button>
            </Space>
          </Form.Item>
        </Form>
      </Card>
    </div>
  )
}
