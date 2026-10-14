import { describe, expect, it } from 'vitest'

import {
  ensureActiveGroupOpen,
  getNavigationItems,
  resolveNavigationState,
  type NavigationGroup,
  type NavigationItem,
} from './navigation'

function leafKeys(items: Array<NavigationItem | NavigationGroup>): string[] {
  return items.flatMap((item) => ('children' in item ? item.children.map((child) => child.key) : [item.key]))
}

describe('sidebar navigation structure', () => {
  it('keeps stable modules grouped while leaving contextual routes out of the menu', () => {
    const items = getNavigationItems('tenant-admin')

    expect(leafKeys(items)).toEqual([
      '/',
      '/providers',
      '/ai-models',
      '/prompts',
      '/knowledge',
      '/agents',
      '/workflows',
      '/plugins',
      '/system/users',
      '/system/roles',
      '/system/audit-logs',
      '/system/tenant',
    ])

    expect(items.map((item) => item.key)).toEqual(['/', 'model-center', 'app-studio', 'governance'])
    expect(items.filter((item) => 'children' in item)).toHaveLength(3)
    expect(leafKeys(items)).not.toContain('/agents/create')
    expect(leafKeys(items)).not.toContain('/workflows/create')
  })

  it('filters entries for tenant members and platform administrators', () => {
    expect(leafKeys(getNavigationItems('tenant-member'))).toEqual([
      '/knowledge',
      '/agents',
      '/workflows',
    ])
    const platformItems = getNavigationItems('platform-admin')
    expect(leafKeys(platformItems)).toEqual(['/admin/tenants'])
    expect(platformItems.every((item) => !('children' in item))).toBe(true)
  })
})

describe('resolveNavigationState', () => {
  const items = getNavigationItems('tenant-admin')

  it.each([
    ['/providers/new', '/providers', 'model-center'],
    ['/providers/provider-1/edit', '/providers', 'model-center'],
    ['/ai-models/new', '/ai-models', 'model-center'],
    ['/ai-models/model-1/edit', '/ai-models', 'model-center'],
    ['/prompts/new', '/prompts', 'app-studio'],
    ['/prompts/prompt-1', '/prompts', 'app-studio'],
    ['/knowledge/kb-1', '/knowledge', 'app-studio'],
    ['/agents/create', '/agents', 'app-studio'],
    ['/agents/agent-1/chat', '/agents', 'app-studio'],
    ['/workflows/create', '/workflows', 'app-studio'],
    ['/workflows/workflow-1/execute', '/workflows', 'app-studio'],
    ['/plugins/plugin-1/config', '/plugins', 'app-studio'],
  ])('maps %s to its owning module entry', (pathname, selectedKey, activeGroupKey) => {
    expect(resolveNavigationState(pathname, items)).toEqual({ selectedKey, activeGroupKey })
  })

  it('matches the dashboard only for the exact root route', () => {
    expect(resolveNavigationState('/', items)).toEqual({ selectedKey: '/' })
    expect(resolveNavigationState('/unknown', items)).toEqual({})
  })

  it('normalizes trailing slashes', () => {
    expect(resolveNavigationState('/system/users/', items)).toEqual({
      selectedKey: '/system/users',
      activeGroupKey: 'governance',
    })
  })
})

describe('ensureActiveGroupOpen', () => {
  it('adds the active group without discarding groups the user already opened', () => {
    expect(ensureActiveGroupOpen(['governance'], 'app-studio')).toEqual(['governance', 'app-studio'])
  })

  it('does not duplicate an already open group', () => {
    expect(ensureActiveGroupOpen(['app-studio'], 'app-studio')).toEqual(['app-studio'])
  })

  it('keeps user expansion state when the route has no visible match', () => {
    expect(ensureActiveGroupOpen(['model-center'], undefined)).toEqual(['model-center'])
  })
})
