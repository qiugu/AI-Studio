import { useState } from 'react'
import { Button, Card, Form, Input, message, Space, Typography } from 'antd'
import { createTenant } from '@/api/admin'
import type { TenantCreateRequest } from '@/types/api'

const { Title, Text } = Typography

export default function TenantList() {
  const [submitting, setSubmitting] = useState(false)
  const [form] = Form.useForm<TenantCreateRequest>()

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields()
      setSubmitting(true)
      const result = await createTenant(values)
      message.success(`租户和管理员账号已创建：${result.data.admin_email}`)
      form.resetFields()
    } catch {
      // API interceptor displays service errors; form errors remain inline.
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div style={{ maxWidth: 640 }}>
      <Title level={4}>创建租户</Title>
      <Card>
        <Form form={form} layout="vertical" onFinish={handleSubmit}>
          <Form.Item
            name="name"
            label="租户名称"
            rules={[{ required: true, message: '请输入租户名称' }]}
          >
            <Input placeholder="如 Acme 公司" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} />
          </Form.Item>
          <Form.Item
            name="admin_email"
            label="首位租户管理员邮箱"
            rules={[
              { required: true, message: '请输入管理员邮箱' },
              { type: 'email', message: '邮箱格式不正确' },
            ]}
          >
            <Input autoComplete="email" />
          </Form.Item>
          <Form.Item
            name="admin_password"
            label="初始密码"
            rules={[
              { required: true, message: '请输入初始密码' },
              { min: 6, message: '密码至少 6 位' },
            ]}
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Space direction="vertical" size={12}>
            <Text type="secondary">创建后，该账号将获得此租户的管理员角色。</Text>
            <Button type="primary" htmlType="submit" loading={submitting}>
              创建租户并授予管理员
            </Button>
          </Space>
        </Form>
      </Card>
    </div>
  )
}
