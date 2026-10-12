import type { ReactNode } from 'react'
import { Navigate } from 'react-router-dom'
import { useAuthStore } from '@/stores/auth'
import { canManageSystem } from '@/utils/permission'

export default function TenantAdminGuard({ children }: { children: ReactNode }) {
  const user = useAuthStore((s) => s.user)
  if (!canManageSystem(user)) return <Navigate to="/" replace />
  return <>{children}</>
}
