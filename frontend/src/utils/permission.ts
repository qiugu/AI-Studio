import type { User } from '@/types/api'

/**
 * 判断当前用户是否具备「系统管理」权限（用户管理、角色权限、审计日志、租户设置）。
 *
 * 系统管理只对当前租户的管理员角色开放；平台管理员只负责创建租户。
 */
export function canManageSystem(user: User | null | undefined): boolean {
  if (!user) return false
  // 管理权限由服务端授予的显式管理员角色表达，不从 owner 字段推导。
  // status 是旧版用户响应中可能缺失的字段；只有显式 false 才表示停用。
  return user.roles?.some((r) => r.is_admin && r.status !== false) ?? false
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
