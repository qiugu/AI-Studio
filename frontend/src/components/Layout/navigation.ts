export type NavigationAudience = 'tenant-member' | 'tenant-admin' | 'platform-admin'

export type NavigationIcon =
  | 'dashboard'
  | 'model-center'
  | 'app-studio'
  | 'governance'
  | 'platform'
  | 'providers'
  | 'models'
  | 'prompts'
  | 'knowledge'
  | 'agents'
  | 'workflows'
  | 'plugins'
  | 'users'
  | 'roles'
  | 'audit'
  | 'tenant'

export interface NavigationItem {
  key: string
  label: string
  icon?: NavigationIcon
}

export interface NavigationGroup {
  key: string
  label: string
  icon: NavigationIcon
  children: NavigationItem[]
}

export type NavigationNode = NavigationItem | NavigationGroup

export interface NavigationState {
  selectedKey?: string
  activeGroupKey?: string
}

interface NavigationDefinition extends NavigationItem {
  audiences: NavigationAudience[]
}

interface NavigationGroupDefinition extends Omit<NavigationGroup, 'children'> {
  audiences: NavigationAudience[]
  children: NavigationDefinition[]
}

type NavigationDefinitionNode = NavigationDefinition | NavigationGroupDefinition

const TENANT_USERS: NavigationAudience[] = ['tenant-member', 'tenant-admin']
const TENANT_ADMINS: NavigationAudience[] = ['tenant-admin']
const PLATFORM_ADMINS: NavigationAudience[] = ['platform-admin']

/**
 * 侧栏只放长期存在的工作区入口。
 * 创建、编辑、详情、对话和执行都是模块内的上下文路由，
 * 由 resolveNavigationState 映射回所属模块。
 */
const navigationDefinitions: NavigationDefinitionNode[] = [
  { key: '/', label: '工作台', icon: 'dashboard', audiences: TENANT_ADMINS },
  {
    key: 'model-center',
    label: '模型中心',
    icon: 'model-center',
    audiences: TENANT_ADMINS,
    children: [
      { key: '/providers', label: '供应商', icon: 'providers', audiences: TENANT_ADMINS },
      { key: '/ai-models', label: '模型', icon: 'models', audiences: TENANT_ADMINS },
    ],
  },
  {
    key: 'app-studio',
    label: '应用开发',
    icon: 'app-studio',
    audiences: TENANT_USERS,
    children: [
      { key: '/prompts', label: 'Prompt', icon: 'prompts', audiences: TENANT_ADMINS },
      { key: '/knowledge', label: '知识库', icon: 'knowledge', audiences: TENANT_USERS },
      { key: '/agents', label: 'Agent', icon: 'agents', audiences: TENANT_USERS },
      { key: '/workflows', label: '工作流', icon: 'workflows', audiences: TENANT_USERS },
      { key: '/plugins', label: '插件', icon: 'plugins', audiences: TENANT_ADMINS },
    ],
  },
  {
    key: 'governance',
    label: '组织管理',
    icon: 'governance',
    audiences: TENANT_ADMINS,
    children: [
      { key: '/system/users', label: '用户', icon: 'users', audiences: TENANT_ADMINS },
      { key: '/system/roles', label: '角色权限', icon: 'roles', audiences: TENANT_ADMINS },
      { key: '/system/audit-logs', label: '审计日志', icon: 'audit', audiences: TENANT_ADMINS },
      { key: '/system/tenant', label: '租户设置', icon: 'tenant', audiences: TENANT_ADMINS },
    ],
  },
  { key: '/admin/tenants', label: '租户管理', icon: 'platform', audiences: PLATFORM_ADMINS },
]

function isGroup(item: NavigationDefinitionNode): item is NavigationGroupDefinition {
  return 'children' in item
}

export function getNavigationItems(audience: NavigationAudience): NavigationNode[] {
  return navigationDefinitions.flatMap((item) => {
    if (!item.audiences.includes(audience)) return []

    if (!isGroup(item)) {
      return [{ key: item.key, label: item.label, icon: item.icon }]
    }

    const children = item.children
      .filter((child) => child.audiences.includes(audience))
      .map(({ key, label, icon }) => ({ key, label, icon }))

    if (children.length === 0) return []
    return [{ key: item.key, label: item.label, icon: item.icon, children }]
  })
}

function normalizePathname(pathname: string) {
  if (pathname === '/') return pathname
  return pathname.replace(/\/+$/, '') || '/'
}

function matchesRoute(pathname: string, key: string) {
  if (key === '/') return pathname === '/'
  return pathname === key || pathname.startsWith(`${key}/`)
}

interface NavigationLeafMatch {
  child: NavigationItem
  groupKey?: string
}

function getLeaves(items: NavigationNode[]): NavigationLeafMatch[] {
  const leaves: NavigationLeafMatch[] = []

  for (const item of items) {
    if ('children' in item) {
      leaves.push(...item.children.map((child) => ({ child, groupKey: item.key })))
    } else {
      leaves.push({ child: item })
    }
  }

  return leaves
}

export function resolveNavigationState(
  pathname: string,
  items: NavigationNode[],
): NavigationState {
  const normalizedPathname = normalizePathname(pathname)
  const match = getLeaves(items)
    .filter(({ child }) => matchesRoute(normalizedPathname, child.key))
    .sort((left, right) => right.child.key.length - left.child.key.length)[0]

  if (!match) return {}

  return {
    selectedKey: match.child.key,
    ...(match.groupKey ? { activeGroupKey: match.groupKey } : {}),
  }
}

export function ensureActiveGroupOpen(openKeys: string[], activeGroupKey?: string): string[] {
  if (!activeGroupKey || openKeys.includes(activeGroupKey)) return openKeys
  return [...openKeys, activeGroupKey]
}
