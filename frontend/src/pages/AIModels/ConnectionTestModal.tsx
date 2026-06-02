import { useState } from 'react'
import { Modal, Form, Input, Button, Alert, Spin, Space, Typography } from 'antd'
import { CheckCircleOutlined, CloseCircleOutlined } from '@ant-design/icons'
import { testProviderConnectivity } from '@/api/ai-model'
import type { ConnectivityTestResult } from '@/types/ai-model'

const { Text } = Typography

interface Props {
  open: boolean
  providerId: number
  onClose: () => void
}

export default function ConnectionTestModal({ open, providerId, onClose }: Props) {
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<ConnectivityTestResult | null>(null)

  const handleTest = async () => {
    const values = await form.validateFields()
    setLoading(true)
    setResult(null)
    try {
      const res = await testProviderConnectivity(providerId, { model_name: values.model_name })
      setResult(res.data)
    } catch {
      setResult({ success: false, latency_ms: null, error: '请求失败，请检查网络' })
    } finally {
      setLoading(false)
    }
  }

  const handleClose = () => {
    form.resetFields()
    setResult(null)
    onClose()
  }

  return (
    <Modal
      title="连接测试"
      open={open}
      onCancel={handleClose}
      footer={null}
      width={480}
    >
      <Form form={form} layout="vertical">
        <Form.Item
          name="model_name"
          label="测试模型"
          rules={[{ required: true, message: '请输入模型名称' }]}
          extra="如：gpt-4o-mini、claude-3-haiku-20240307"
        >
          <Input placeholder="输入模型名称" />
        </Form.Item>
        <Form.Item>
          <Button type="primary" onClick={handleTest} loading={loading} block>
            开始测试
          </Button>
        </Form.Item>
      </Form>

      {loading && (
        <div style={{ textAlign: 'center', padding: '16px 0' }}>
          <Spin tip="正在测试连接..." />
        </div>
      )}

      {result && !loading && (
        result.success ? (
          <Alert
            type="success"
            icon={<CheckCircleOutlined />}
            showIcon
            message="连接成功"
            description={
              <Space direction="vertical">
                <Text>供应商连接正常</Text>
                {result.latency_ms != null && (
                  <Text type="secondary">响应延迟: {result.latency_ms} ms</Text>
                )}
              </Space>
            }
          />
        ) : (
          <Alert
            type="error"
            icon={<CloseCircleOutlined />}
            showIcon
            message="连接失败"
            description={result.error || '未知错误'}
          />
        )
      )}
    </Modal>
  )
}
