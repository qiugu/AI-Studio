import type { User } from '@/types/api'

/**
 * 判断当前用户是否具备「系统管理」权限（用户管理、角色权限、审计日志、租户设置）。
 *
 * 规则与侧边栏菜单可见性保持一致：平台超级管理员，或拥有 admin 角色
 * （角色 code 含 'admin'）的租户管理员可见；普通租户成员返回 false。
 */
export function canManageSystem(user: User | null | undefined): boolean {
  if (!user) return false
  if (user.is_platform_admin) return true
  // 租户所有者（注册创建者）：管理能力由 owner_id 推导
  if (user.is_tenant_owner) return true
  // 显式管理员角色，替代原先按角色 code 子串判断的脆弱做法
  return user.roles?.some((r) => r.is_admin) ?? false
}

export function hasPermission(
  permissions: Array<{ resource: string; action: string }>,
  resource: string,
  action: string,
): boolean {
  return permissions.some((p) => p.resource === resource && p.action === action)
}

export function hasAnyPermission(
  permissions: Array<{ resource: string; action: string }>,
  checks: Array<{ resource: string; action: string }>,
): boolean {
  return checks.some((check) => hasPermission(permissions, check.resource, check.action))
}

export function hasAllPermissions(
  permissions: Array<{ resource: string; action: string }>,
  checks: Array<{ resource: string; action: string }>,
): boolean {
  return checks.every((check) => hasPermission(permissions, check.resource, check.action))
}