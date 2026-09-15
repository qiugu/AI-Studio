import { useState } from 'react'
import { Form, Input, Button, Card, Typography, message, Tabs, Alert } from 'antd'
import { MailOutlined, LockOutlined, UserOutlined, SafetyCertificateOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '@/stores/auth'
import { getErrorMessage } from '@/utils/request'

const { Title } = Typography

interface LoginFormValues {
  email: string
  password: string
}

interface RegisterFormValues {
  email: string
  nickname?: string
  password: string
  password_repeat: string
}

/** 登录被「邮箱未验证」拦截时的提示文案特征，用于区分并引导验证。 */
const UNVERIFIED_HINT = /(邮箱尚未验证|请.*验证.*邮箱|验证邮件)/

export default function Login() {
  const navigate = useNavigate()
  const login = useAuthStore((s) => s.login)
  const register = useAuthStore((s) => s.register)
  const loading = useAuthStore((s) => s.loading)
  const [activeTab, setActiveTab] = useState('login')
  // 邮箱未验证被拒时记录邮箱，展示「去验证」引导
  const [unverifiedEmail, setUnverifiedEmail] = useState<string | null>(null)

  const handleLogin = async (values: LoginFormValues) => {
    setUnverifiedEmail(null)
    try {
      await login(values.email, values.password)
      message.success('登录成功')
      navigate('/')
    } catch (err) {
      // 错误提示已由全局响应拦截器统一弹出；此处仅区分「未验证邮箱」场景做引导
      const msg = getErrorMessage(err)
      if (UNVERIFIED_HINT.test(msg)) {
        setUnverifiedEmail(values.email)
      }
    }
  }

  const handleRegister = async (values: RegisterFormValues) => {
    try {
      await register(values.email, values.password, values.password_repeat, values.nickname)
      // 注册成功进入邮箱验证流程，不再自动登录
      const devToken = useAuthStore.getState().pendingVerification?.devToken ?? null
      message.success('注册成功，请验证邮箱以激活账号')
      navigate('/verify-email', { state: { email: values.email, devToken } })
    } catch {
      // 错误提示已由全局响应拦截器统一弹出，此处无需重复处理
    }
  }

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
      }}
    >
      <Card style={{ width: 420, boxShadow: '0 8px 24px rgba(0,0,0,0.12)' }}>
        {unverifiedEmail && (
          <Alert
            type="warning"
            showIcon
            style={{ marginBottom: 16 }}
            message="邮箱尚未验证"
            description={
              <div>
                <div>该账号已完成注册但未验证邮箱，请先完成验证后再登录。</div>
                <Button
                  type="link"
                  size="small"
                  icon={<SafetyCertificateOutlined />}
                  style={{ paddingLeft: 0 }}
                  onClick={() =>
                    navigate(`/verify-email?email=${encodeURIComponent(unverifiedEmail)}`)
                  }
                >
                  去验证邮箱
                </Button>
              </div>
            }
          />
        )}
        <div style={{ textAlign: 'center', marginBottom: 24 }}>
          <Title level={3} style={{ marginBottom: 4 }}>
            AI Studio
          </Title>
          <p style={{ color: '#999' }}>企业级 AI 应用平台</p>
        </div>

        <Tabs
          activeKey={activeTab}
          onChange={setActiveTab}
          centered
          items={[
            { key: 'login', label: '登录' },
            { key: 'register', label: '注册' },
          ]}
        />

        {activeTab === 'login' ? (
          <Form<LoginFormValues> onFinish={handleLogin} size="large" autoComplete="off">
            <Form.Item name="email" rules={[{ required: true, message: '请输入邮箱' }, { type: 'email', message: '请输入有效的邮箱' }]}>
              <Input prefix={<MailOutlined />} placeholder="邮箱" />
            </Form.Item>
            <Form.Item name="password" rules={[{ required: true, message: '请输入密码' }]}>
              <Input.Password prefix={<LockOutlined />} placeholder="密码" />
            </Form.Item>
            <Form.Item>
              <Button type="primary" htmlType="submit" block loading={loading}>
                登录
              </Button>
            </Form.Item>
          </Form>
        ) : (
          <Form<RegisterFormValues>
            onFinish={handleRegister}
            size="large"
            autoComplete="off"
          >
            <Form.Item name="email" rules={[{ required: true, message: '请输入邮箱' }, { type: 'email', message: '请输入有效的邮箱' }]}>
              <Input prefix={<MailOutlined />} placeholder="邮箱" />
            </Form.Item>
            <Form.Item name="nickname">
              <Input prefix={<UserOutlined />} placeholder="昵称（可选）" />
            </Form.Item>
            <Form.Item name="password" rules={[{ required: true, message: '请输入密码' }, { min: 6, message: '密码至少6位' }]}>
              <Input.Password prefix={<LockOutlined />} placeholder="密码" />
            </Form.Item>
            <Form.Item
              name="password_repeat"
              dependencies={['password']}
              rules={[
                { required: true, message: '请确认密码' },
                ({ getFieldValue }) => ({
                  validator(_, value) {
                    if (!value || getFieldValue('password') === value) {
                      return Promise.resolve()
                    }
                    return Promise.reject(new Error('两次密码不一致'))
                  },
                }),
              ]}
            >
              <Input.Password prefix={<LockOutlined />} placeholder="确认密码" />
            </Form.Item>
            <Form.Item>
              <Button type="primary" htmlType="submit" block loading={loading}>
                注册
              </Button>
            </Form.Item>
          </Form>
        )}
      </Card>
    </div>
  )
}