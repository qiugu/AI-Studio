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