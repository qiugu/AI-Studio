export const SECRET_NAME_HINTS = [
  'key',
  'secret',
  'token',
  'password',
  'pwd',
  'credential',
  'authorization',
  'auth',
] as const

export function isSensitiveConfigName(name: string): boolean {
  const normalized = name.toLowerCase()
  return SECRET_NAME_HINTS.some((hint) => normalized.includes(hint))
}

export function containsSensitiveConfig(value: unknown, nameHint = ''): boolean {
  if (nameHint && isSensitiveConfigName(nameHint)) return value !== null && value !== undefined
  if (Array.isArray(value)) return value.some((item) => containsSensitiveConfig(item))
  if (!value || typeof value !== 'object') return false
  return Object.entries(value).some(([name, item]) => (
    isSensitiveConfigName(name) || containsSensitiveConfig(item, name)
  ))
}

export function requiresPluginConfigReauth(
  items: Array<{ name: string; value: unknown }>,
  removedNames: string[] = [],
): boolean {
  return items.some((item) => containsSensitiveConfig(item.value, item.name))
    || removedNames.some((name) => isSensitiveConfigName(name))
}

export function requiresProviderReauth(apiKey: unknown, config: unknown): boolean {
  return (apiKey !== undefined && apiKey !== null) || containsSensitiveConfig(config)
}

export function requiresRoleUpdateReauth(currentStatus: boolean, nextStatus: boolean): boolean {
  return currentStatus !== nextStatus
}
