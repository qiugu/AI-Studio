import { useMemo, useState, type ReactNode } from 'react'
import { Layout, Menu, type MenuProps } from 'antd'
import {
  DashboardOutlined,
  ApiOutlined,
  RobotOutlined,
  CodeOutlined,
  DatabaseOutlined,
  ThunderboltOutlined,
  AppstoreOutlined,
  TeamOutlined,
  SettingOutlined,
  SafetyOutlined,
  FileTextOutlined,
  BranchesOutlined,
  AppstoreAddOutlined,
} from '@ant-design/icons'
import { useNavigate, useLocation } from 'react-router-dom'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'
import { canManageSystem } from '@/utils/permission'
import {
  getNavigationItems,
  ensureActiveGroupOpen,
  resolveNavigationState,
  type NavigationAudience,
  type NavigationIcon,
  type NavigationNode,
} from './navigation'
import './Sidebar.css'

const { Sider } = Layout

const navigationIcons: Record<NavigationIcon, ReactNode> = {
  dashboard: <DashboardOutlined />,
  'model-center': <ApiOutlined />,
  'app-studio': <AppstoreAddOutlined />,
  governance: <SettingOutlined />,
  platform: <SafetyOutlined />,
  providers: <ApiOutlined />,
  models: <RobotOutlined />,
  prompts: <CodeOutlined />,
  knowledge: <DatabaseOutlined />,
  agents: <ThunderboltOutlined />,
  workflows: <BranchesOutlined />,
  plugins: <AppstoreOutlined />,
  users: <TeamOutlined />,
  roles: <SafetyOutlined />,
  audit: <FileTextOutlined />,
  tenant: <SettingOutlined />,
}

function toMenuItems(items: NavigationNode[]): MenuProps['items'] {
  return items.map((item) => {
    if ('children' in item) {
      return {
        key: item.key,
        icon: navigationIcons[item.icon],
        label: item.label,
        children: item.children.map((child) => ({
          key: child.key,
          icon: child.icon ? navigationIcons[child.icon] : undefined,
          label: child.label,
        })),
      }
    }

    return {
      key: item.key,
      icon: item.icon ? navigationIcons[item.icon] : undefined,
      label: item.label,
    }
  })
}

export default function Sidebar() {
  const collapsed = useAppStore((s) => s.sidebarCollapsed)
  const user = useAuthStore((s) => s.user)
  const navigate = useNavigate()
  const location = useLocation()

  const isPlatformAdmin = Boolean(user?.is_platform_admin)
  const isTenantAdmin = canManageSystem(user)

  const audience: NavigationAudience = isPlatformAdmin
    ? 'platform-admin'
    : isTenantAdmin
      ? 'tenant-admin'
      : 'tenant-member'
  const navigationItems = useMemo(() => getNavigationItems(audience), [audience])
  const menuItems = useMemo(() => toMenuItems(navigationItems), [navigationItems])
  const navigationState = useMemo(
    () => resolveNavigationState(location.pathname, navigationItems),
    [location.pathname, navigationItems],
  )
  const [openKeys, setOpenKeys] = useState<string[]>([])
  const visibleOpenKeys = useMemo(
    () => ensureActiveGroupOpen(openKeys, navigationState.activeGroupKey),
    [openKeys, navigationState.activeGroupKey],
  )

  const handleMenuClick = ({ key }: { key: string }) => {
    if (key.startsWith('/')) {
      navigate(key)
    }
  }

  return (
    <Sider
      className="app-sidebar"
      trigger={null}
      collapsible
      collapsed={collapsed}
      collapsedWidth={72}
      width={248}
    >
      <div className="app-sidebar__brand" aria-label="AI Studio">
        <div className="app-sidebar__mark">AI</div>
        {!collapsed && (
          <div className="app-sidebar__brand-copy">
            <strong>AI Studio</strong>
            <span>Enterprise workspace</span>
          </div>
        )}
      </div>
      <Menu
        aria-label="主导航"
        className="app-sidebar__menu"
        theme="dark"
        mode="inline"
        selectedKeys={navigationState.selectedKey ? [navigationState.selectedKey] : []}
        openKeys={collapsed ? [] : visibleOpenKeys}
        items={menuItems}
        onClick={handleMenuClick}
        onOpenChange={(keys) => setOpenKeys(keys)}
      />
    </Sider>
  )
}
