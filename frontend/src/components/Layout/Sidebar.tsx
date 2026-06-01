import { Layout, Menu } from 'antd'
import {
  DashboardOutlined,
  RobotOutlined,
  CodeOutlined,
  DatabaseOutlined,
  ApartmentOutlined,
  ThunderboltOutlined,
  AppstoreOutlined as PluginOutlined,
  SettingOutlined,
  TeamOutlined,
  SafetyOutlined,
  FileTextOutlined,
} from '@ant-design/icons'
import { useNavigate, useLocation } from 'react-router-dom'
import { useAppStore } from '@/stores/app'

const { Sider } = Layout

const menuItems = [
  { key: '/', icon: <DashboardOutlined />, label: '仪表盘' },
  {
    key: 'ai-group',
    icon: <RobotOutlined />,
    label: 'AI 模型',
    children: [
      { key: '/providers', label: '供应商管理' },
      { key: '/ai-models', label: '模型管理' },
    ],
  },
  { key: '/prompts', icon: <CodeOutlined />, label: 'Prompt 管理' },
  { key: '/knowledge', icon: <DatabaseOutlined />, label: '知识库' },
  { key: '/workflows', icon: <ApartmentOutlined />, label: '工作流' },
  { key: '/agents', icon: <ThunderboltOutlined />, label: 'Agent' },
  { key: '/plugins', icon: <PluginOutlined />, label: '插件' },
  {
    key: 'system-group',
    icon: <SettingOutlined />,
    label: '系统管理',
    children: [
      { key: '/system/users', icon: <TeamOutlined />, label: '用户管理' },
      { key: '/system/roles', icon: <SafetyOutlined />, label: '角色权限' },
      { key: '/system/audit-logs', icon: <FileTextOutlined />, label: '审计日志' },
    ],
  },
]

export default function Sidebar() {
  const collapsed = useAppStore((s) => s.sidebarCollapsed)
  const navigate = useNavigate()
  const location = useLocation()

  const handleMenuClick = ({ key }: { key: string }) => {
    if (key.startsWith('/')) {
      navigate(key)
    }
  }

  return (
    <Sider
      trigger={null}
      collapsible
      collapsed={collapsed}
      width={220}
      style={{
        overflow: 'auto',
        height: '100vh',
        position: 'fixed',
        left: 0,
        top: 0,
        bottom: 0,
        zIndex: 100,
      }}
    >
      <div
        style={{
          height: 64,
          display: 'flex',
          alignItems: 'center',
          justifyContent: collapsed ? 'center' : 'flex-start',
          padding: collapsed ? '0' : '0 24px',
          color: '#fff',
          fontSize: collapsed ? 16 : 18,
          fontWeight: 700,
          whiteSpace: 'nowrap',
          overflow: 'hidden',
        }}
      >
        {collapsed ? 'AI' : 'AI Studio'}
      </div>
      <Menu
        theme="dark"
        mode="inline"
        selectedKeys={[location.pathname]}
        defaultOpenKeys={['ai-group', 'system-group']}
        items={menuItems}
        onClick={handleMenuClick}
      />
    </Sider>
  )
}