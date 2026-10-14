import type { User } from '@/types/api'

/**
 * 判断当前用户是否具备「系统管理」权限（用户管理、角色权限、审计日志、租户设置）。
 *
 * 系统管理只对当前租户的管理员角色开放；平台管理员只负责创建租户。
 */
export function canManageSystem(user: User | null | undefined): boolean {
  if (!user) return false
  if (user.is_platform_admin) return false
  return hasAnyPermission(
    user.capabilities ?? [],
    [
      { resource: 'tenant', action: 'members_manage' },
      { resource: 'tenant', action: 'roles_manage' },
      { resource: 'tenant', action: 'settings' },
    ],
  )
}

export function hasPermission(
  permissions: Array<{ resource: string; action: string }> | string[],
  resource: string,
  action: string,
): boolean {
  return permissions.some((p) =>
    typeof p === 'string'
      ? p === `${resource}.${action}`
      : p.resource === resource && p.action === action,
  )
}

export function hasAnyPermission(
  permissions: Array<{ resource: string; action: string }> | string[],
  checks: Array<{ resource: string; action: string }>,
): boolean {
  return checks.some((check) => hasPermission(permissions, check.resource, check.action))
}

export function hasAllPermissions(
  permissions: Array<{ resource: string; action: string }> | string[],
  checks: Array<{ resource: string; action: string }>,
): boolean {
  return checks.every((check) => hasPermission(permissions, check.resource, check.action))
}
