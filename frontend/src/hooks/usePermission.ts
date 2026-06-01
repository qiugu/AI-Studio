import { useCallback } from 'react'
import { useAuthStore } from '@/stores/auth'
import { hasPermission, hasAnyPermission, hasAllPermissions } from '@/utils/permission'

export function usePermission() {
  const user = useAuthStore((s) => s.user)
  const permissions = user?.roles?.flatMap((r) => r.permissions) || []

  const check = useCallback(
    (resource: string, action: string) => hasPermission(permissions, resource, action),
    [permissions],
  )

  const checkAny = useCallback(
    (checks: Array<{ resource: string; action: string }>) => hasAnyPermission(permissions, checks),
    [permissions],
  )

  const checkAll = useCallback(
    (checks: Array<{ resource: string; action: string }>) => hasAllPermissions(permissions, checks),
    [permissions],
  )

  return { check, checkAny, checkAll, permissions }
}