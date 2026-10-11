import { describe, expect, it } from 'vitest'

import {
  getNavigationItems,
  keepActiveGroupOpen,
  resolveNavigationState,
  type NavigationItem,
} from './navigation'

function leafKeys(items: NavigationItem[]): string[] {
  return items.flatMap((item) => ('children' in item ? item.children.map((child) => child.key) : [item.key]))
}

describe('sidebar navigation structure', () => {
  it('keeps stable resources in groups and leaves contextual actions out of the menu', () => {
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
    expect(leafKeys(items)).not.toContain('/workflows/create')
  })

  it('filters entries for tenant members and platform administrators', () => {
    expect(leafKeys(getNavigationItems('tenant-member'))).toEqual([
      '/knowledge',
      '/agents',
      '/workflows',
    ])
    expect(leafKeys(getNavigationItems('platform-admin'))).toEqual(['/admin/tenants'])
  })
})

describe('resolveNavigationState', () => {
  const items = getNavigationItems('tenant-admin')

  it.each([
    ['/providers/new', '/providers', 'resources-group'],
    ['/ai-models/model-1/edit', '/ai-models', 'resources-group'],
    ['/prompts/prompt-1', '/prompts', 'resources-group'],
    ['/knowledge/kb-1', '/knowledge', 'resources-group'],
    ['/agents/create', '/agents', 'apps-group'],
    ['/agents/agent-1/chat', '/agents', 'apps-group'],
    ['/workflows/workflow-1/execute', '/workflows', 'apps-group'],
    ['/plugins/plugin-1/config', '/plugins', 'apps-group'],
  ])('maps %s to the stable %s entry', (pathname, selectedKey, activeGroupKey) => {
    expect(resolveNavigationState(pathname, items)).toEqual({ selectedKey, activeGroupKey })
  })

  it('matches the dashboard only for the exact root route', () => {
    expect(resolveNavigationState('/', items)).toEqual({ selectedKey: '/' })
    expect(resolveNavigationState('/unknown', items)).toEqual({})
  })

  it('normalizes trailing slashes', () => {
    expect(resolveNavigationState('/system/users/', items)).toEqual({
      selectedKey: '/system/users',
      activeGroupKey: 'system-group',
    })
  })
})

describe('keepActiveGroupOpen', () => {
  it('opens the active group without discarding other expanded groups', () => {
    expect(keepActiveGroupOpen(['system-group'], 'apps-group')).toEqual([
      'system-group',
      'apps-group',
    ])
  })

  it('does not duplicate an already expanded active group', () => {
    expect(keepActiveGroupOpen(['apps-group'], 'apps-group')).toEqual(['apps-group'])
  })

  it('keeps the current expansion when a route has no menu entry', () => {
    expect(keepActiveGroupOpen(['resources-group'], undefined)).toEqual(['resources-group'])
  })
})
