import type { ReactNode } from 'react'
import { Navigate } from 'react-router-dom'
import { useAuthStore } from '@/stores/auth'

export default function TenantUserGuard({ children }: { children: ReactNode }) {
  const isPlatformAdmin = useAuthStore((s) => s.user?.is_platform_admin)
  if (isPlatformAdmin) return <Navigate to="/admin/tenants" replace />
  return <>{children}</>
}
