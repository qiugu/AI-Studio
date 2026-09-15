import { describe, it, expect } from 'vitest'
import * as pluginMeta from './pluginMeta'
import type { PluginSourceType } from '@/types/plugin'

const SOURCE_TYPES: PluginSourceType[] = ['http', 'mcp', 'skill']

describe('pluginMeta', () => {
  it('接入方式元数据与类型定义完全一致（无遗漏、无多余）', () => {
    expect(Object.keys(pluginMeta.PLUGIN_SOURCE_META).sort()).toEqual(
      [...SOURCE_TYPES].sort()
    )
  })

  it('每个取值都具备展示所需字段', () => {
    for (const item of Object.values(pluginMeta.PLUGIN_SOURCE_META)) {
      expect(item.label).toBeTruthy()
      expect(item.description).toBeTruthy()
      expect(item.useCases).toBeTruthy()
      expect(item.color).toBeTruthy()
    }
  })

  it('下拉选项由元数据派生，value 与 label 完整', () => {
    expect(pluginMeta.PLUGIN_SOURCE_OPTIONS.map((o) => o.value)).toEqual(SOURCE_TYPES)
    for (const opt of pluginMeta.PLUGIN_SOURCE_OPTIONS) expect(opt.label).toBeTruthy()
  })

  it('已登记取值返回对应中文名', () => {
    expect(pluginMeta.pluginSourceMeta('http').label).toBe('HTTP / OpenAPI')
    expect(pluginMeta.pluginSourceMeta('mcp').label).toBe('MCP 协议')
  })

  it('未知取值降级为原值展示，不抛错', () => {
    expect(pluginMeta.pluginSourceMeta('grpc').label).toBe('grpc')
    expect(pluginMeta.pluginSourceMeta(undefined).label).toBe('—')
    expect(pluginMeta.pluginSourceMeta(null).label).toBe('—')
  })

  it('原型链键不被误判为已登记取值', () => {
    expect(pluginMeta.pluginSourceMeta('toString').label).toBe('toString')
  })

  it('能力形态 plugin_type 相关导出已随 M2.0 移除', () => {
    expect('PLUGIN_TYPE_META' in pluginMeta).toBe(false)
    expect('PLUGIN_TYPE_OPTIONS' in pluginMeta).toBe(false)
    expect('pluginTypeMeta' in pluginMeta).toBe(false)
  })
})
