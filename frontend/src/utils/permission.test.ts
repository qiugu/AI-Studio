import { describe, it, expect } from 'vitest'
import { canManageSystem } from './permission'
import type { User, Role } from '@/types/api'

function makeUser(overrides: Partial<User> = {}): User {
  return {
    id: 'u1',
    tenant_id: 't1',
    email: 'a@b.com',
    nickname: 'tester',
    is_platform_admin: false,
    email_verified: true,
    is_tenant_owner: false,
    last_login_at: null,
    created_at: null,
    roles: [],
    ...overrides,
  } as User
}

function role(code: string, is_admin = false): Role {
  return {
    id: code,
    name: code,
    code,
    description: null,
    status: true,
    is_admin,
    permissions: [],
  } as Role
}

describe('canManageSystem', () => {
  it('普通租户成员（无任何角色）不可见系统管理', () => {
    expect(canManageSystem(makeUser({ roles: [] }))).toBe(false)
  })

  it('普通租户成员（非 admin 角色）不可见系统管理', () => {
    expect(canManageSystem(makeUser({ roles: [role('member')] }))).toBe(false)
  })

  it('未登录 / 无用户信息时不可见系统管理', () => {
    expect(canManageSystem(null)).toBe(false)
    expect(canManageSystem(undefined)).toBe(false)
  })

  it('租户管理员（is_admin 角色）可见系统管理', () => {
    expect(canManageSystem(makeUser({ roles: [role('tenant_admin', true)] }))).toBe(true)
  })

  it('角色 code 含 admin 但 is_admin=false 时不可见（不再按 code 子串判断）', () => {
    expect(canManageSystem(makeUser({ roles: [role('tenant_admin', false)] }))).toBe(false)
  })

  it('平台超级管理员（is_platform_admin）可见系统管理', () => {
    expect(canManageSystem(makeUser({ is_platform_admin: true, roles: [] }))).toBe(true)
  })

  it('租户所有者（is_tenant_owner）可见系统管理', () => {
    expect(canManageSystem(makeUser({ is_tenant_owner: true, roles: [] }))).toBe(true)
  })
})
