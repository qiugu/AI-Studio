import { describe, expect, it } from 'vitest'

import type { AgentTool, ToolCatalogPlugin } from '@/types/agent'
import {
  buildToolDescription,
  buildToolName,
  isDestructiveMethod,
  missingSelectionKeys,
  selectionKey,
  selectionsToToolPayload,
  splitSelectionKey,
  summarizeBoundTools,
  toolsToSelectionKeys,
} from './agentToolBinding'

const catalog: ToolCatalogPlugin[] = [
  {
    id: 'p-weather',
    name: 'Weather',
    source_type: 'http',
    description: '天气查询服务',
    icon: null,
    is_public: false,
    endpoints: [
      { id: 'e-search', endpoint: '/v1/search', method: 'GET', description: '查询城市天气', is_destructive: false },
      { id: 'e-purge', endpoint: '/v1/cache', method: 'DELETE', description: '清空缓存', is_destructive: true },
    ],
  },
  {
    id: 'p-cn-name',
    name: '订单处理',
    source_type: 'http',
    description: '订单系统对接',
    icon: null,
    is_public: true,
    endpoints: [
      { id: 'e-create', endpoint: '/orders', method: 'POST', description: '创建订单', is_destructive: false },
    ],
  },
]

describe('isDestructiveMethod', () => {
  it('识别破坏性动词，且大小写与空白不敏感', () => {
    expect(isDestructiveMethod('DELETE')).toBe(true)
    expect(isDestructiveMethod('put')).toBe(true)
    expect(isDestructiveMethod(' Patch ')).toBe(true)
  })

  it('读写类动词不算破坏性', () => {
    expect(isDestructiveMethod('GET')).toBe(false)
    expect(isDestructiveMethod('POST')).toBe(false)
    expect(isDestructiveMethod('')).toBe(false)
  })
})

describe('selectionKey / splitSelectionKey', () => {
  it('往返一致', () => {
    const key = selectionKey('p1', 'e1')
    expect(key).toBe('p1::e1')
    expect(splitSelectionKey(key)).toEqual({ pluginId: 'p1', endpointId: 'e1' })
  })

  it('非法键返回 null 而不抛错', () => {
    expect(splitSelectionKey('')).toBeNull()
    expect(splitSelectionKey('no-separator')).toBeNull()
    expect(splitSelectionKey('::e1')).toBeNull()
    expect(splitSelectionKey('p1::')).toBeNull()
  })

  it('端点 id 含分隔符时按首个分隔符切分', () => {
    expect(splitSelectionKey('p1::e::1')).toEqual({ pluginId: 'p1', endpointId: 'e::1' })
  })
})

describe('buildToolName', () => {
  it('中文插件名收敛为 ASCII 安全名，保证 function name 合法', () => {
    const name = buildToolName(catalog[1], catalog[1].endpoints[0])
    expect(name).toMatch(/^[A-Za-z0-9_-]{1,64}$/)
    // 中文 slug 为空时退回插件 id 前 8 位，仍可辨识
    expect(name).toContain('p-cn-nam')
  })

  it('ASCII 插件名保留可读性', () => {
    expect(buildToolName(catalog[0], catalog[0].endpoints[0])).toBe(
      'Weather-GET-v1-search'
    )
  })

  it('长度不超过 64 且不以分隔符结尾', () => {
    const long: ToolCatalogPlugin = {
      ...catalog[0],
      name: 'a'.repeat(80),
      endpoints: [{ ...catalog[0].endpoints[0], endpoint: '/very/'.repeat(10) }],
    }
    const name = buildToolName(long, long.endpoints[0])
    expect(name.length).toBeLessThanOrEqual(64)
    expect(name.endsWith('-')).toBe(false)
  })
})

describe('selectionsToToolPayload', () => {
  it('只读端点生成 plugin 工具，且不带 allow_destructive', () => {
    const payload = selectionsToToolPayload(
      [selectionKey('p-weather', 'e-search')],
      catalog
    )
    expect(payload).toHaveLength(1)
    expect(payload[0].tool_type).toBe('plugin')
    expect(payload[0].config).toEqual({
      plugin_id: 'p-weather',
      endpoint_id: 'e-search',
      endpoint: '/v1/search',
      method: 'GET',
    })
    expect(payload[0].is_enabled).toBe(true)
  })

  it('破坏性端点写入 allow_destructive: true —— 勾选动作即显式授权', () => {
    const payload = selectionsToToolPayload(
      [selectionKey('p-weather', 'e-purge')],
      catalog
    )
    expect(payload[0].config).toMatchObject({ endpoint_id: 'e-purge', allow_destructive: true })
  })

  it('目录中不存在或格式非法的选择项被跳过', () => {
    const payload = selectionsToToolPayload(
      ['p-missing::e1', 'garbage', selectionKey('p-weather', 'e-ghost')],
      catalog
    )
    expect(payload).toHaveLength(0)
  })

  it('生成同名工具时只保留一个，避免模型侧互相覆盖', () => {
    const duplicated: ToolCatalogPlugin[] = [
      { ...catalog[0], id: 'p-dup', name: 'Weather' },
    ]
    const payload = selectionsToToolPayload(
      [selectionKey('p-weather', 'e-search'), selectionKey('p-dup', 'e-search')],
      duplicated
    )
    // duplicated 中只含 p-dup，p-weather 不在目录 → 仅 1 条
    expect(payload).toHaveLength(1)
    expect(payload[0].config).toMatchObject({ plugin_id: 'p-dup' })
  })
})

describe('buildToolDescription', () => {
  it('包含中文插件名与具体操作，供模型选择工具', () => {
    const description = buildToolDescription(catalog[1], catalog[1].endpoints[0])
    expect(description).toContain('订单处理')
    expect(description).toContain('POST /orders')
    expect(description).toContain('订单系统对接')
  })
})

describe('toolsToSelectionKeys', () => {
  it('从已授权工具还原选择项', () => {
    const tools = [
      {
        id: 't1',
        agent_id: 'a1',
        tenant_id: 'tenant-1',
        tool_type: 'plugin',
        config: { plugin_id: 'p-weather', endpoint_id: 'e-search' },
        name: 'Weather-GET-v1-search',
        description: '天气',
        is_enabled: true,
        created_at: '',
        updated_at: '',
      },
    ] as unknown as AgentTool[]

    expect(toolsToSelectionKeys(tools, catalog)).toEqual(['p-weather::e-search'])
  })

  it('历史数据仅有 endpoint 路径时按目录匹配补全 endpoint_id', () => {
    const tools = [
      {
        tool_type: 'plugin',
        config: { plugin_id: 'p-weather', endpoint: '/v1/cache' },
      },
    ] as unknown as AgentTool[]

    expect(toolsToSelectionKeys(tools, catalog)).toEqual(['p-weather::e-purge'])
  })

  it('忽略非 plugin 类型与缺少 plugin_id 的条目', () => {
    const tools = [
      { tool_type: 'knowledge', config: { knowledge_base_id: 'kb1' } },
      { tool_type: 'plugin', config: {} },
    ] as unknown as AgentTool[]

    expect(toolsToSelectionKeys(tools, catalog)).toEqual([])
    expect(toolsToSelectionKeys(null, catalog)).toEqual([])
  })
})

describe('missingSelectionKeys', () => {
  it('标出目录中已失效的授权，便于提示用户重新选择', () => {
    const keys = [
      selectionKey('p-weather', 'e-search'),
      selectionKey('p-weather', 'e-ghost'),
      selectionKey('p-deleted', 'e1'),
      'garbage',
    ]
    expect(missingSelectionKeys(keys, catalog)).toEqual([
      selectionKey('p-weather', 'e-ghost'),
      selectionKey('p-deleted', 'e1'),
      'garbage',
    ])
  })

  it('全部有效时返回空数组', () => {
    expect(missingSelectionKeys([selectionKey('p-weather', 'e-search')], catalog)).toEqual([])
  })
})

describe('summarizeBoundTools', () => {
  it('只汇总 plugin 类工具并给出可读操作', () => {
    const tools = [
      {
        tool_type: 'plugin',
        name: 'Weather-GET-v1-search',
        description: 'Weather｜GET /v1/search',
        config: { method: 'GET', endpoint: '/v1/search' },
      },
      { tool_type: 'knowledge', name: 'kb', description: null, config: {} },
    ] as unknown as AgentTool[]

    expect(summarizeBoundTools(tools)).toEqual([
      { plugin: 'Weather｜GET /v1/search', action: 'GET /v1/search' },
    ])
  })
})
