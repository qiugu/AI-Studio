import type { Plugin, PluginConfigItem } from '@/types/plugin'

export type ReadinessTone = 'ready' | 'attention' | 'muted'

export interface PluginReadiness {
  label: string
  action: string
  tone: ReadinessTone
}

export interface SetupStep {
  key: 'connect' | 'capabilities' | 'test' | 'activate'
  label: string
  hint: string
  status: 'complete' | 'current' | 'upcoming'
}

export interface ConnectionFields {
  baseUrl: string
  apiKey: string
  headersText: string
}

export function getPluginReadiness(plugin: Plugin): PluginReadiness {
  if (plugin.status !== 'active') {
    return { label: '已暂停', action: '查看设置', tone: 'muted' }
  }
  if (!plugin.endpoints?.length) {
    return { label: '还需添加能力', action: '继续设置', tone: 'attention' }
  }
  return { label: '可以给 Agent 使用', action: '设置与试用', tone: 'ready' }
}

export function getSetupProgress(input: {
  hasConnection: boolean
  endpointCount: number
  testSucceeded: boolean
}): SetupStep[] {
  const definitions: Array<Omit<SetupStep, 'status'> & { complete: boolean }> = [
    {
      key: 'connect',
      label: '连接服务',
      hint: '填写访问地址与凭据',
      complete: input.hasConnection,
    },
    {
      key: 'capabilities',
      label: '添加能力',
      hint: '选择 Agent 可以完成的操作',
      complete: input.endpointCount > 0,
    },
    {
      key: 'test',
      label: '试用一次',
      hint: '确认插件返回预期结果',
      complete: input.testSucceeded,
    },
    {
      key: 'activate',
      label: '给 Agent 使用',
      hint: '在 Agent 中开启所需能力',
      complete: false,
    },
  ]

  const currentIndex = definitions.findIndex((step) => !step.complete)
  return definitions.map(({ complete, ...step }, index) => ({
    ...step,
    status: complete && index < currentIndex
      ? 'complete'
      : index === currentIndex
        ? 'current'
        : 'upcoming',
  }))
}

export function splitConnectionConfig(items: PluginConfigItem[]): {
  fields: ConnectionFields
  advanced: Record<string, unknown>
  hasValueByName: Record<string, boolean>
} {
  const values = Object.fromEntries(items.map((item) => [item.name, item.value]))
  const hasValueByName = Object.fromEntries(
    items.map((item) => [item.name, Boolean(item.has_value)])
  )
  const advanced = Object.fromEntries(
    items
      .filter((item) => !['base_url', 'api_key', 'headers'].includes(item.name))
      .map((item) => [item.name, item.value])
  )

  return {
    fields: {
      baseUrl: typeof values.base_url === 'string' ? values.base_url : '',
      apiKey: '',
      headersText: JSON.stringify(values.headers || {}, null, 2),
    },
    advanced,
    hasValueByName,
  }
}

export function buildConnectionConfigItems(input: {
  fields: ConnectionFields
  advanced: Record<string, unknown>
  hasExistingApiKey: boolean
}): PluginConfigItem[] {
  const items: PluginConfigItem[] = []
  const baseUrl = input.fields.baseUrl.trim()
  const apiKey = input.fields.apiKey.trim()
  const headersText = input.fields.headersText.trim()

  if (baseUrl) items.push({ name: 'base_url', value: baseUrl })
  if (apiKey || !input.hasExistingApiKey) {
    if (apiKey) items.push({ name: 'api_key', value: apiKey })
  }
  if (headersText) {
    items.push({ name: 'headers', value: JSON.parse(headersText) })
  }

  for (const [name, value] of Object.entries(input.advanced)) {
    if (value !== null && value !== undefined && value !== '') {
      items.push({ name, value })
    }
  }
  return items
}
