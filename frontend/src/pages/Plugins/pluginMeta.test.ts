import { describe, it, expect } from 'vitest'
import {
  PLUGIN_SOURCE_META,
  PLUGIN_SOURCE_OPTIONS,
  PLUGIN_TYPE_META,
  PLUGIN_TYPE_OPTIONS,
  pluginSourceMeta,
  pluginTypeMeta,
} from './pluginMeta'
import type { PluginSourceType, PluginType } from '@/types/plugin'

const PLUGIN_TYPES: PluginType[] = ['tool', 'connector', 'processor']
const SOURCE_TYPES: PluginSourceType[] = ['http', 'mcp', 'skill']

describe('pluginMeta', () => {
  it('能力形态元数据与类型定义完全一致（无遗漏、无多余）', () => {
    expect(Object.keys(PLUGIN_TYPE_META).sort()).toEqual([...PLUGIN_TYPES].sort())
  })

  it('接入方式元数据与类型定义完全一致', () => {
    expect(Object.keys(PLUGIN_SOURCE_META).sort()).toEqual([...SOURCE_TYPES].sort())
  })

  it('每个取值都具备展示所需字段', () => {
    const all = [...Object.values(PLUGIN_TYPE_META), ...Object.values(PLUGIN_SOURCE_META)]
    for (const item of all) {
      expect(item.label).toBeTruthy()
      expect(item.description).toBeTruthy()
      expect(item.useCases).toBeTruthy()
      expect(item.color).toBeTruthy()
    }
  })

  it('provider 已从能力形态中移除', () => {
    expect(PLUGIN_TYPE_META).not.toHaveProperty('provider')
  })

  it('下拉选项由元数据派生，value 与 label 完整', () => {
    expect(PLUGIN_TYPE_OPTIONS.map((o) => o.value)).toEqual(PLUGIN_TYPES)
    expect(PLUGIN_SOURCE_OPTIONS.map((o) => o.value)).toEqual(SOURCE_TYPES)
    for (const opt of PLUGIN_TYPE_OPTIONS) expect(opt.label).toContain(opt.value)
  })

  it('已登记取值返回对应中文名', () => {
    expect(pluginTypeMeta('connector').label).toBe('连接器')
    expect(pluginSourceMeta('mcp').label).toBe('MCP 协议')
  })

  it('未知取值降级为原值展示，不抛错', () => {
    expect(pluginTypeMeta('provider').label).toBe('provider')
    expect(pluginSourceMeta('grpc').label).toBe('grpc')
    expect(pluginTypeMeta(undefined).label).toBe('—')
    expect(pluginSourceMeta(null).label).toBe('—')
  })

  it('原型链键不被误判为已登记取值', () => {
    expect(pluginTypeMeta('constructor').label).toBe('constructor')
    expect(pluginSourceMeta('toString').label).toBe('toString')
  })
})
