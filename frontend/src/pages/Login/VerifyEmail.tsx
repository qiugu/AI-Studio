import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Alert, Button, Card, Form, Input, Spin, Typography, message } from 'antd'
import { MailOutlined, SafetyCertificateOutlined } from '@ant-design/icons'
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { useAuthStore } from '@/stores/auth'
import { resendVerification } from '@/api/auth'

const { Title, Paragraph, Text } = Typography

/**
 * 邮箱验证页（受控自助注册流程的第二步）。
 *
 * - 邮件链接带 ?token= 进入时，自动验证并免登录进入系统；
 * - 否则提示查收邮件，并提供：
 *   1) 开发态（未配置 SMTP）下后端返回的 verification_token，可一键激活；
 *   2) 手动粘贴令牌；
 *   3) 按邮箱重发验证邮件。
 */
export default function VerifyEmail() {
  const navigate = useNavigate()
  const location = useLocation()
  const [searchParams] = useSearchParams()
  const verifyAndLogin = useAuthStore((s) => s.verifyAndLogin)
  const pending = useAuthStore((s) => s.pendingVerification)

  const token = searchParams.get('token') ?? ''
  const emailFromQuery = searchParams.get('email') ?? ''
  const state = (location.state ?? {}) as { email?: string; devToken?: string | null }
  const email = state.email ?? pending?.email ?? emailFromQuery ?? ''
  const devToken = state.devToken ?? pending?.devToken ?? null

  const [verifying, setVerifying] = useState(false)
  const [resendEmail, setResendEmail] = useState(email)
  const [resending, setResending] = useState(false)
  const [manualToken, setManualToken] = useState(devToken ?? '')
  const [resendDevToken, setResendDevToken] = useState<string | null>(null)

  // 防止 React StrictMode 下 effect 双调用导致重复验证
  const verifiedRef = useRef(false)

  const doVerify = async (tk: string) => {
    if (!tk) return
    setVerifying(true)
    try {
      await verifyAndLogin(tk)
      message.success('邮箱验证成功，已自动登录')
      navigate('/', { replace: true })
    } catch {
      // 全局响应拦截器已弹出具体错误，保留在当前页以便重试
    } finally {
      setVerifying(false)
    }
  }

  useEffect(() => {
    if (token && !verifiedRef.current) {
      verifiedRef.current = true
      doVerify(token)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token])

  const handleResend = async () => {
    setResending(true)
    try {
      const res = await resendVerification(resendEmail)
      const tok = res.data?.verification_token ?? null
      if (tok) {
        // 开发态：未配置 SMTP，直接拿到令牌，可一键激活
        setResendDevToken(tok)
        setManualToken(tok)
        message.info('开发模式：未配置 SMTP，已返回验证令牌，可直接激活')
      } else {
        setResendDevToken(null)
        message.success('验证邮件已发送，请前往邮箱查收')
      }
    } catch {
      // 全局响应拦截器已弹出具体错误
    } finally {
      setResending(false)
    }
  }

  if (verifying) {
    return (
      <Centered>
        <Card style={{ width: 420, textAlign: 'center' }}>
          <Spin size="large" />
          <Paragraph style={{ marginTop: 16, marginBottom: 0 }}>
            正在验证邮箱，请稍候…
          </Paragraph>
        </Card>
      </Centered>
    )
  }

  const activeDevToken = devToken ?? resendDevToken ?? null

  return (
    <Centered>
      <Card style={{ width: 440, boxShadow: '0 8px 24px rgba(0,0,0,0.12)' }}>
        <div style={{ textAlign: 'center', marginBottom: 16 }}>
          <SafetyCertificateOutlined style={{ fontSize: 40, color: '#1677ff' }} />
          <Title level={3} style={{ margin: '12px 0 4px' }}>
            验证你的邮箱
          </Title>
          <Paragraph type="secondary" style={{ marginBottom: 0 }}>
            注册成功，请完成邮箱验证以激活账号
          </Paragraph>
        </div>

        {email && (
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 16 }}
            message="验证邮件已发送"
            description={
              <span>
                我们已向 <Text strong>{email}</Text> 发送了一封验证邮件，请点击邮件中的链接完成激活。
              </span>
            }
          />
        )}

        {activeDevToken && (
          <Form layout="vertical" style={{ marginBottom: 16 }}>
            <Alert
              type="warning"
              showIcon
              message="开发模式：未配置 SMTP"
              description="当前环境未配置邮件服务，下方为验证令牌，可直接激活账号。"
              style={{ marginBottom: 12 }}
            />
            <Form.Item label="验证令牌" style={{ marginBottom: 8 }}>
              <Input.TextArea value={activeDevToken} autoSize readOnly />
            </Form.Item>
            <Button
              type="primary"
              block
              icon={<SafetyCertificateOutlined />}
              onClick={() => doVerify(activeDevToken)}
            >
              立即激活
            </Button>
          </Form>
        )}

        {!activeDevToken && (
          <Form layout="vertical" style={{ marginBottom: 16 }}>
            <Form.Item label="或粘贴验证令牌" style={{ marginBottom: 8 }}>
              <Input
                placeholder="将邮件链接中的令牌或开发态令牌粘贴此处"
                value={manualToken}
                onChange={(e) => setManualToken(e.target.value)}
                prefix={<SafetyCertificateOutlined />}
              />
            </Form.Item>
            <Button
              type="primary"
              block
              disabled={!manualToken}
              onClick={() => doVerify(manualToken)}
            >
              激活账号
            </Button>
          </Form>
        )}

        <Form layout="vertical">
          <Form.Item label="重发验证邮件" style={{ marginBottom: 8 }}>
            <Input
              placeholder="输入注册邮箱"
              value={resendEmail}
              onChange={(e) => setResendEmail(e.target.value)}
              prefix={<MailOutlined />}
            />
          </Form.Item>
          <Button block onClick={handleResend} loading={resending}>
            重发验证邮件
          </Button>
        </Form>

        <div style={{ textAlign: 'center', marginTop: 16 }}>
          <Button type="link" onClick={() => navigate('/login')}>
            返回登录
          </Button>
        </div>
      </Card>
    </Centered>
  )
}

function Centered({ children }: { children: ReactNode }) {
  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
        padding: 16,
      }}
    >
      {children}
    </div>
  )
}
