import { useMemo, useState, type ReactNode } from 'react'
import { Layout, Menu, type MenuProps } from 'antd'
import {
  DashboardOutlined,
  RobotOutlined,
  SettingOutlined,
  SafetyOutlined,
  BranchesOutlined,
} from '@ant-design/icons'
import { useNavigate, useLocation } from 'react-router-dom'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'
import { canManageSystem } from '@/utils/permission'
import {
  getNavigationItems,
  keepActiveGroupOpen,
  resolveNavigationState,
  type NavigationAudience,
  type NavigationIcon,
  type NavigationItem,
} from './navigation'

const { Sider } = Layout

const navigationIcons: Record<NavigationIcon, ReactNode> = {
  dashboard: <DashboardOutlined />,
  resources: <RobotOutlined />,
  apps: <BranchesOutlined />,
  system: <SettingOutlined />,
  platform: <SafetyOutlined />,
}

function toMenuItems(items: NavigationItem[]): MenuProps['items'] {
  return items.map((item) => ({
    key: item.key,
    icon: item.icon ? navigationIcons[item.icon] : undefined,
    label: item.label,
    ...('children' in item
      ? {
          children: item.children.map((child) => ({
            key: child.key,
            label: child.label,
          })),
        }
      : {}),
  }))
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
  const [menuOpenState, setMenuOpenState] = useState(() => ({
    pathname: location.pathname,
    openKeys: navigationState.activeGroupKey ? [navigationState.activeGroupKey] : [],
  }))

  if (menuOpenState.pathname !== location.pathname) {
    setMenuOpenState((current) => ({
      pathname: location.pathname,
      openKeys: keepActiveGroupOpen(current.openKeys, navigationState.activeGroupKey),
    }))
  }

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
        selectedKeys={navigationState.selectedKey ? [navigationState.selectedKey] : []}
        openKeys={collapsed ? [] : menuOpenState.openKeys}
        items={menuItems}
        onClick={handleMenuClick}
        onOpenChange={(keys) => {
          if (!collapsed) {
            setMenuOpenState({ pathname: location.pathname, openKeys: keys })
          }
        }}
      />
    </Sider>
  )
}
