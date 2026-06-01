import type { ReactNode } from 'react'
import { usePermission } from '@/hooks/usePermission'

interface PermissionGuardProps {
  resource: string
  action: string
  children: ReactNode
  fallback?: ReactNode
}

export default function PermissionGuard({
  resource,
  action,
  children,
  fallback = null,
}: PermissionGuardProps) {
  const { check } = usePermission()

  if (!check(resource, action)) {
    return <>{fallback}</>
  }

  return <>{children}</>
}