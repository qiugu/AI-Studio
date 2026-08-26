import { Layout, Menu } from 'antd'
import {
  DashboardOutlined,
  RobotOutlined,
  CodeOutlined,
  DatabaseOutlined,
  ThunderboltOutlined,
  AppstoreOutlined as PluginOutlined,
  SettingOutlined,
  TeamOutlined,
  SafetyOutlined,
  FileTextOutlined,
  BranchesOutlined,
} from '@ant-design/icons'
import { useNavigate, useLocation } from 'react-router-dom'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'

const { Sider } = Layout

const baseMenuItems = [
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
  {
    key: 'workflows-group',
    icon: <BranchesOutlined />,
    label: '工作流',
    children: [
      { key: '/workflows', label: '工作流列表' },
      { key: '/workflows/create', label: '创建工作流' },
    ],
  },
  { key: '/agents', icon: <ThunderboltOutlined />, label: 'Agent' },
  { key: '/plugins', icon: <PluginOutlined />, label: '插件' },
]

const systemMenuGroup = {
  key: 'system-group',
  icon: <SettingOutlined />,
  label: '系统管理',
  children: [
    { key: '/system/users', icon: <TeamOutlined />, label: '用户管理' },
    { key: '/system/roles', icon: <SafetyOutlined />, label: '角色权限' },
    { key: '/system/audit-logs', icon: <FileTextOutlined />, label: '审计日志' },
    { key: '/system/tenant', icon: <SettingOutlined />, label: '租户设置' },
  ],
}

const adminMenuGroup = {
  key: 'admin-group',
  icon: <SafetyOutlined />,
  label: '平台管理',
  children: [
    { key: '/admin/tenants', icon: <TeamOutlined />, label: '租户管理' },
  ],
}

export default function Sidebar() {
  const collapsed = useAppStore((s) => s.sidebarCollapsed)
  const user = useAuthStore((s) => s.user)
  const isPlatformAdmin = useAuthStore((s) => s.user?.is_platform_admin)
  const navigate = useNavigate()
  const location = useLocation()

  // 系统管理与平台管理仅对（租户/平台）管理员可见
  const canManage =
    isPlatformAdmin || (user?.roles?.some((r) => r.code.includes('admin')) ?? false)

  const menuItems = [
    ...baseMenuItems,
    ...(canManage ? [systemMenuGroup] : []),
    ...(isPlatformAdmin ? [adminMenuGroup] : []),
  ]

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
        // defaultOpenKeys={['ai-group', 'system-group']}
        items={menuItems}
        onClick={handleMenuClick}
      />
    </Sider>
  )
}