/**
 * Agent 工具授权：纯逻辑层（无 React 依赖，便于单测）。
 *
 * 设计要点：
 *
 * 1. **授权单位是「插件 + 端点」**，不是插件。可调用性的原子单位是 endpoint——
 *    选中某插件的某端点，模型才可能调用它；只选插件会让"暴露了哪些具体操作"对用户不可见，
 *    也无法精确拦截 DELETE / PUT / PATCH 这类高危端点。
 *
 * 2. **破坏性端点的启用发生在选择那一刻**。用户勾选一个 DELETE 端点，即视为一次显式授权
 *    （UI 需先二次确认），落库时写入 `allow_destructive: true`；后端门禁因此仍具约束力，
 *    而不是被前端悄悄绕过。
 *
 * 3. **工具名生成必须 ASCII 安全**。`name` 会作为 function name 传给模型，
 *    OpenAI 兼容接口要求 `^[a-zA-Z0-9_-]{1,64}$`；插件名常为中文，直接拼接会导致调用被拒。
 *    因此 name 走 sanitize，可读的中文描述放进 `description`（模型靠它选择工具）。
 */
import type {
  AgentTool,
  AgentToolCreate,
  ToolCatalogEndpoint,
  ToolCatalogPlugin,
} from '@/types/agent'

/** 破坏性 HTTP 动词。须与后端 `plugin_policy.DESTRUCTIVE_HTTP_METHODS` 保持一致。 */
const DESTRUCTIVE_METHODS = new Set(['DELETE', 'PUT', 'PATCH'])

/** 工具名长度上限，与 OpenAI function name 约束一致。 */
const MAX_TOOL_NAME_LENGTH = 64

/** 是否为破坏性动词（大小写与空白不敏感）。 */
export function isDestructiveMethod(method: string): boolean {
  return DESTRUCTIVE_METHODS.has((method || '').trim().toUpperCase())
}

/** 选择项唯一键。以「插件 :: 端点」为原子单位，避免不同插件的同名端点相互覆盖。 */
export function selectionKey(pluginId: string, endpointId: string): string {
  return `${pluginId}::${endpointId}`
}

/** 拆分选择项键；非法格式返回 null（不抛错，交由调用方跳过）。 */
export function splitSelectionKey(
  key: string
): { pluginId: string; endpointId: string } | null {
  const separator = '::'
  const index = (key || '').indexOf(separator)
  if (index <= 0) return null
  const pluginId = key.slice(0, index)
  const endpointId = key.slice(index + separator.length)
  if (!pluginId || !endpointId) return null
  return { pluginId, endpointId }
}

/** 把任意文本收敛为 `[A-Za-z0-9-]`，供工具名使用。 */
function slugify(text: string): string {
  return text
    .replace(/[^A-Za-z0-9]+/g, '-')
    .replace(/-+/g, '-')
    .replace(/^-+|-+$/g, '')
}

/**
 * 生成 ASCII 安全的工具名。
 *
 * 插件名含中文时 slug 会为空，此时退回 `plugin-{id 前 8 位}` 以保证唯一性与可读性下限。
 */
export function buildToolName(
  plugin: ToolCatalogPlugin,
  endpoint: ToolCatalogEndpoint
): string {
  const head = slugify(plugin.name) || `plugin-${plugin.id.slice(0, 8)}`
  const tail = [slugify(endpoint.method), slugify(endpoint.endpoint)]
    .filter(Boolean)
    .join('-')
  const composed = tail ? `${head}-${tail}` : head
  return composed.slice(0, MAX_TOOL_NAME_LENGTH).replace(/-+$/g, '')
}

/** 生成给模型看的工具描述：中文插件名 + 具体操作 + 插件自述。 */
export function buildToolDescription(
  plugin: ToolCatalogPlugin,
  endpoint: ToolCatalogEndpoint
): string {
  const action = `${endpoint.method.toUpperCase()} ${endpoint.endpoint}`
  const parts = [`${plugin.name}｜${action}`]
  if (endpoint.description) parts.push(endpoint.description)
  if (plugin.description) parts.push(plugin.description)
  return parts.join('　')
}

/**
 * 把选择项键转换为提交给后端的工具载荷。
 *
 * 目录中已不存在的选择项会被跳过——调用方应先用 `missingSelectionKeys` 提示用户，
 * 而不是让这次静默丢弃成为「以为配上了」的来源。
 */
export function selectionsToToolPayload(
  keys: string[],
  catalog: ToolCatalogPlugin[]
): AgentToolCreate[] {
  const pluginById = new Map(catalog.map((plugin) => [plugin.id, plugin]))
  const usedNames = new Set<string>()
  const payload: AgentToolCreate[] = []

  for (const key of keys) {
    const parsed = splitSelectionKey(key)
    if (!parsed) continue

    const plugin = pluginById.get(parsed.pluginId)
    const endpoint = plugin?.endpoints.find((item) => item.id === parsed.endpointId)
    if (!plugin || !endpoint) continue

    const name = buildToolName(plugin, endpoint)
    // 同名工具在模型侧会互相覆盖，保留先出现的那个。
    if (usedNames.has(name)) continue
    usedNames.add(name)

    const destructive = isDestructiveMethod(endpoint.method)
    payload.push({
      tool_type: 'plugin',
      name,
      description: buildToolDescription(plugin, endpoint),
      is_enabled: true,
      config: {
        plugin_id: plugin.id,
        endpoint_id: endpoint.id,
        // 同时冗余路径与方法：便于列表展示与「清单漂移」比对，
        // 运行时的唯一事实源仍是 endpoint_id。
        endpoint: endpoint.endpoint,
        method: endpoint.method,
        ...(destructive ? { allow_destructive: true } : {}),
      },
    })
  }

  return payload
}

/**
 * 从已有工具条目还原选择项键，用于编辑态回填。
 *
 * 历史数据可能只写了 `endpoint` 路径而无 `endpoint_id`（早期 API 直写），
 * 此时借助目录按路径匹配补全，避免用户打开编辑页看到「什么都没选」。
 */
export function toolsToSelectionKeys(
  tools: AgentTool[] | null | undefined,
  catalog: ToolCatalogPlugin[] = []
): string[] {
  const keys: string[] = []

  for (const tool of tools || []) {
    if (tool.tool_type !== 'plugin') continue
    const config = (tool.config || {}) as Record<string, unknown>
    const pluginId = typeof config.plugin_id === 'string' ? config.plugin_id : ''
    if (!pluginId) continue

    let endpointId =
      typeof config.endpoint_id === 'string' ? config.endpoint_id : ''

    if (!endpointId && typeof config.endpoint === 'string') {
      const plugin = catalog.find((item) => item.id === pluginId)
      endpointId =
        plugin?.endpoints.find((item) => item.endpoint === config.endpoint)?.id ?? ''
    }

    if (endpointId) keys.push(selectionKey(pluginId, endpointId))
  }

  return keys
}

/**
 * 找出在目录中已失效的选择项（插件被删除、停用或端点被移除）。
 *
 * 交给调用方给出明确提示，而不是静默丢弃——静默丢弃正是「失效授权无声扩散」的成因。
 */
export function missingSelectionKeys(
  keys: string[],
  catalog: ToolCatalogPlugin[]
): string[] {
  const pluginById = new Map(catalog.map((plugin) => [plugin.id, plugin]))
  return keys.filter((key) => {
    const parsed = splitSelectionKey(key)
    if (!parsed) return true
    const plugin = pluginById.get(parsed.pluginId)
    if (!plugin) return true
    return !plugin.endpoints.some((item) => item.id === parsed.endpointId)
  })
}

/** 汇总已授权工具的可读标签，用于 Agent 列表的能力提示。 */
export function summarizeBoundTools(
  tools: AgentTool[] | null | undefined
): { plugin: string; action: string }[] {
  return (tools || [])
    .filter((tool) => tool.tool_type === 'plugin')
    .map((tool) => {
      const config = (tool.config || {}) as Record<string, unknown>
      const endpoint = typeof config.endpoint === 'string' ? config.endpoint : ''
      const method = typeof config.method === 'string' ? config.method : ''
      return {
        plugin: tool.description || tool.name,
        action: [method.toUpperCase(), endpoint].filter(Boolean).join(' '),
      }
    })
}
