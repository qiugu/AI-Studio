import { useState } from 'react'
import { Layout, Avatar, Dropdown, Space, Button, Tooltip, Form, Input, Modal, message } from 'antd'
import { MenuFoldOutlined, MenuUnfoldOutlined, UserOutlined, LogoutOutlined, LockOutlined } from '@ant-design/icons'
import { changeMyPassword } from '@/api/auth'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'
import { useNavigate } from 'react-router-dom'

const { Header: AntHeader } = Layout

export default function Header() {
  const collapsed = useAppStore((s) => s.sidebarCollapsed)
  const toggleSidebar = useAppStore((s) => s.toggleSidebar)
  const user = useAuthStore((s) => s.user)
  const logout = useAuthStore((s) => s.logout)
  const navigate = useNavigate()
  const [passwordModalOpen, setPasswordModalOpen] = useState(false)
  const [passwordSubmitting, setPasswordSubmitting] = useState(false)
  const [passwordForm] = Form.useForm()

  const handleLogout = async () => {
    await logout()
    navigate('/login')
  }

  const dropdownItems = [
    {
      key: 'change-password',
      icon: <LockOutlined />,
      label: '修改密码',
    },
    {
      key: 'profile',
      icon: <UserOutlined />,
      label: '个人信息',
    },
    {
      type: 'divider' as const,
    },
    {
      key: 'logout',
      icon: <LogoutOutlined />,
      label: '退出登录',
      danger: true,
    },
  ]

  const handleDropdownClick = ({ key }: { key: string }) => {
    if (key === 'logout') {
      handleLogout()
    } else if (key === 'change-password') {
      passwordForm.resetFields()
      setPasswordModalOpen(true)
    }
  }

  const handlePasswordSubmit = async () => {
    try {
      const values = await passwordForm.validateFields()
      setPasswordSubmitting(true)
      await changeMyPassword(values.current_password, values.new_password)
      message.success('密码已修改，请重新登录')
      setPasswordModalOpen(false)
      await logout()
      navigate('/login')
    } catch {
      // interceptor handles API errors; validation errors remain inline.
    } finally {
      setPasswordSubmitting(false)
    }
  }

  return (
    <AntHeader
      style={{
        padding: '0 24px',
        background: 'var(--app-color-surface-strong)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        boxShadow: '0 1px 4px rgba(8, 29, 44, 0.1)',
      }}
    >
      <Tooltip title={collapsed ? '展开侧栏' : '收起侧栏'}>
        <Button
          type="text"
          aria-label={collapsed ? '展开侧栏' : '收起侧栏'}
          icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
          onClick={toggleSidebar}
        />
      </Tooltip>
      <Dropdown
        trigger={['click']}
        menu={{ items: dropdownItems, onClick: handleDropdownClick }}
        placement="bottomRight"
      >
        <Space style={{ cursor: 'pointer' }}>
          <Avatar icon={<UserOutlined />} src={user?.avatar || undefined} size="small" />
          <span>{user?.nickname || user?.email || '未登录'}</span>
        </Space>
      </Dropdown>
      <Modal
        title="修改我的密码"
        open={passwordModalOpen}
        onOk={handlePasswordSubmit}
        onCancel={() => setPasswordModalOpen(false)}
        okText="保存密码"
        cancelText="取消"
        confirmLoading={passwordSubmitting}
        destroyOnHidden
      >
        <Form form={passwordForm} layout="vertical">
          <Form.Item
            name="current_password"
            label="当前密码"
            rules={[{ required: true, message: '请输入当前密码' }]}
          >
            <Input.Password placeholder="当前密码" />
          </Form.Item>
          <Form.Item
            name="new_password"
            label="新密码"
            rules={[{ required: true, min: 12, message: '密码至少 12 位' }]}
          >
            <Input.Password placeholder="至少 12 位" />
          </Form.Item>
          <Form.Item
            name="password_repeat"
            label="确认新密码"
            dependencies={['new_password']}
            rules={[
              { required: true, message: '请再次输入新密码' },
              ({ getFieldValue }) => ({
                validator(_, value) {
                  return !value || getFieldValue('new_password') === value
                    ? Promise.resolve()
                    : Promise.reject(new Error('两次输入的密码不一致'))
                },
              }),
            ]}
          >
            <Input.Password placeholder="再次输入新密码" />
          </Form.Item>
        </Form>
      </Modal>
    </AntHeader>
  )
}
