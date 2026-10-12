import { Layout, Avatar, Dropdown, Space, Button, Tooltip } from 'antd'
import { MenuFoldOutlined, MenuUnfoldOutlined, UserOutlined, LogoutOutlined } from '@ant-design/icons'
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

  const handleLogout = async () => {
    await logout()
    navigate('/login')
  }

  const dropdownItems = [
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
      <Dropdown menu={{ items: dropdownItems, onClick: handleDropdownClick }} placement="bottomRight">
        <Space style={{ cursor: 'pointer' }}>
          <Avatar icon={<UserOutlined />} src={user?.avatar || undefined} size="small" />
          <span>{user?.nickname || user?.email || '未登录'}</span>
        </Space>
      </Dropdown>
    </AntHeader>
  )
}
