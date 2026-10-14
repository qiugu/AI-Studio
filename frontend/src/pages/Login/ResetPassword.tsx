import { useState } from 'react'
import { Alert, Button, Card, Form, Input, Typography, message } from 'antd'
import { LockOutlined } from '@ant-design/icons'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { completePasswordReset } from '@/api/auth'

const { Title, Paragraph } = Typography

interface ResetPasswordFormValues {
  password: string
  password_repeat: string
}

export default function ResetPassword() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const token = searchParams.get('token')
  const [completed, setCompleted] = useState(false)

  const handleSubmit = async (values: ResetPasswordFormValues) => {
    if (!token) return
    try {
      await completePasswordReset(token, values.password)
      setCompleted(true)
      message.success('密码已重置，请使用新密码登录')
    } catch {
      // interceptor handles error toast
    }
  }

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'linear-gradient(135deg, var(--app-color-primary-strong) 0%, var(--app-color-primary) 100%)',
      }}
    >
      <Card style={{ width: 420, boxShadow: '0 8px 24px rgba(0,0,0,0.12)' }}>
        <Title level={3}>设置新密码</Title>
        {!token ? (
          <Alert type="error" showIcon message="重置链接无效" description="请让管理员重新发起密码重置。" />
        ) : completed ? (
          <>
            <Alert type="success" showIcon message="密码重置成功" description="旧会话已失效，请使用新密码重新登录。" />
            <Button type="primary" block style={{ marginTop: 20 }} onClick={() => navigate('/login')}>
              返回登录
            </Button>
          </>
        ) : (
          <>
            <Paragraph type="secondary">重置链接 1 小时内有效，设置成功后旧登录会话将失效。</Paragraph>
            <Form<ResetPasswordFormValues> layout="vertical" onFinish={handleSubmit} autoComplete="off">
              <Form.Item
                name="password"
                label="新密码"
                rules={[{ required: true, min: 12, message: '密码至少 12 位' }]}
              >
                <Input.Password prefix={<LockOutlined />} placeholder="至少 12 位" />
              </Form.Item>
              <Form.Item
                name="password_repeat"
                label="确认新密码"
                dependencies={['password']}
                rules={[
                  { required: true, message: '请再次输入新密码' },
                  ({ getFieldValue }) => ({
                    validator(_, value) {
                      return !value || getFieldValue('password') === value
                        ? Promise.resolve()
                        : Promise.reject(new Error('两次输入的密码不一致'))
                    },
                  }),
                ]}
              >
                <Input.Password prefix={<LockOutlined />} placeholder="再次输入新密码" />
              </Form.Item>
              <Button type="primary" htmlType="submit" block>
                设置新密码
              </Button>
            </Form>
          </>
        )}
      </Card>
    </div>
  )
}
