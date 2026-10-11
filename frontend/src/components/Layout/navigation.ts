export type NavigationAudience = 'tenant-member' | 'tenant-admin' | 'platform-admin'

export type NavigationIcon = 'dashboard' | 'resources' | 'apps' | 'system' | 'platform'

type NavigationVisibility = NavigationAudience[]

export interface NavigationLeaf {
  key: string
  label: string
  icon?: NavigationIcon
}

export interface NavigationGroup {
  key: string
  label: string
  icon: NavigationIcon
  children: NavigationLeaf[]
}

export type NavigationItem = NavigationLeaf | NavigationGroup

export interface NavigationState {
  selectedKey?: string
  activeGroupKey?: string
}

interface NavigationLeafDefinition extends NavigationLeaf {
  audiences: NavigationVisibility
}

interface NavigationGroupDefinition extends Omit<NavigationGroup, 'children'> {
  audiences: NavigationVisibility
  children: NavigationLeafDefinition[]
}

type NavigationDefinition = NavigationLeafDefinition | NavigationGroupDefinition

const TENANT_USERS: NavigationVisibility = ['tenant-member', 'tenant-admin']
const TENANT_ADMINS: NavigationVisibility = ['tenant-admin']
const PLATFORM_ADMINS: NavigationVisibility = ['platform-admin']

const navigationDefinitions: NavigationDefinition[] = [
  {
    key: '/',
    label: '仪表盘',
    icon: 'dashboard',
    audiences: TENANT_ADMINS,
  },
  {
    key: 'resources-group',
    label: 'AI 资源',
    icon: 'resources',
    audiences: TENANT_USERS,
    children: [
      { key: '/providers', label: '供应商管理', audiences: TENANT_ADMINS },
      { key: '/ai-models', label: '模型管理', audiences: TENANT_ADMINS },
      { key: '/prompts', label: 'Prompt 管理', audiences: TENANT_ADMINS },
      { key: '/knowledge', label: '知识库', audiences: TENANT_USERS },
    ],
  },
  {
    key: 'apps-group',
    label: '应用与编排',
    icon: 'apps',
    audiences: TENANT_USERS,
    children: [
      { key: '/agents', label: 'Agent', audiences: TENANT_USERS },
      { key: '/workflows', label: '工作流', audiences: TENANT_USERS },
      { key: '/plugins', label: '插件', audiences: TENANT_ADMINS },
    ],
  },
  {
    key: 'system-group',
    label: '系统管理',
    icon: 'system',
    audiences: TENANT_ADMINS,
    children: [
      { key: '/system/users', label: '用户管理', audiences: TENANT_ADMINS },
      { key: '/system/roles', label: '角色权限', audiences: TENANT_ADMINS },
      { key: '/system/audit-logs', label: '审计日志', audiences: TENANT_ADMINS },
      { key: '/system/tenant', label: '租户设置', audiences: TENANT_ADMINS },
    ],
  },
  {
    key: 'admin-group',
    label: '平台管理',
    icon: 'platform',
    audiences: PLATFORM_ADMINS,
    children: [
      { key: '/admin/tenants', label: '创建租户', audiences: PLATFORM_ADMINS },
    ],
  },
]

function isGroup(item: NavigationDefinition): item is NavigationGroupDefinition {
  return 'children' in item
}

function isVisible(audiences: NavigationVisibility, audience: NavigationAudience) {
  return audiences.includes(audience)
}

export function getNavigationItems(audience: NavigationAudience): NavigationItem[] {
  return navigationDefinitions.flatMap((item) => {
    if (!isVisible(item.audiences, audience)) return []

    if (!isGroup(item)) {
      return [{ key: item.key, label: item.label, icon: item.icon }]
    }

    const children = item.children.flatMap((child) => {
      if (!isVisible(child.audiences, audience)) return []
      return [{ key: child.key, label: child.label, icon: child.icon }]
    })

    if (children.length === 0) return []
    return [{ key: item.key, label: item.label, icon: item.icon, children }]
  })
}

function normalizePathname(pathname: string) {
  if (pathname === '/') return pathname
  return pathname.replace(/\/+$/, '') || '/'
}

function matchesLeaf(pathname: string, key: string) {
  if (key === '/') return pathname === '/'
  return pathname === key || pathname.startsWith(`${key}/`)
}

export function resolveNavigationState(
  pathname: string,
  items: NavigationItem[],
): NavigationState {
  const normalizedPathname = normalizePathname(pathname)
  const candidates: Array<NavigationState & { matchLength: number }> = []

  for (const item of items) {
    if ('children' in item) {
      for (const child of item.children) {
        if (matchesLeaf(normalizedPathname, child.key)) {
          candidates.push({
            selectedKey: child.key,
            activeGroupKey: item.key,
            matchLength: child.key.length,
          })
        }
      }
    } else if (matchesLeaf(normalizedPathname, item.key)) {
      candidates.push({ selectedKey: item.key, matchLength: item.key.length })
    }
  }

  const match = candidates.sort((left, right) => right.matchLength - left.matchLength)[0]
  if (!match) return {}

  return {
    selectedKey: match.selectedKey,
    ...(match.activeGroupKey ? { activeGroupKey: match.activeGroupKey } : {}),
  }
}

export function keepActiveGroupOpen(
  openKeys: string[],
  activeGroupKey?: string,
): string[] {
  if (!activeGroupKey || openKeys.includes(activeGroupKey)) return openKeys
  return [...openKeys, activeGroupKey]
}
