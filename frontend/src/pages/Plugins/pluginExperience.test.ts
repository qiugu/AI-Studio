import { describe, expect, it } from 'vitest'

import type { Plugin, PluginConfigItem } from '@/types/plugin'
import {
  buildConnectionConfigItems,
  getPluginReadiness,
  getSetupProgress,
  splitConnectionConfig,
} from './pluginExperience'

function plugin(partial: Partial<Plugin> = {}): Plugin {
  return {
    id: 'plugin-1',
    tenant_id: 'tenant-1',
    name: '企业搜索',
    source_type: 'http',
    version: '1.0.0',
    status: 'active',
    is_public: false,
    endpoints: [],
    ...partial,
  }
}

describe('plugin experience helpers', () => {
  it('用用户能理解的状态提示插件下一步', () => {
    expect(getPluginReadiness(plugin())).toMatchObject({
      label: '还需添加能力',
      action: '继续设置',
    })

    expect(
      getPluginReadiness(
        plugin({ endpoints: [{ id: 'ep-1', plugin_id: 'plugin-1', endpoint: '/search', method: 'GET' }] })
      )
    ).toMatchObject({
      label: '可以给 Agent 使用',
      action: '设置与试用',
    })

    expect(getPluginReadiness(plugin({ status: 'disabled' }))).toMatchObject({
      label: '已暂停',
      action: '查看设置',
    })
  })

  it('按真实完成情况生成四步使用进度', () => {
    const steps = getSetupProgress({
      hasConnection: true,
      endpointCount: 2,
      testSucceeded: false,
    })

    expect(steps.map((step) => step.label)).toEqual([
      '连接服务',
      '添加能力',
      '试用一次',
      '给 Agent 使用',
    ])
    expect(steps.map((step) => step.status)).toEqual([
      'complete',
      'complete',
      'current',
      'upcoming',
    ])
  })

  it('把常用连接项与高级设置分开，同时记住已保存的密钥', () => {
    const items: PluginConfigItem[] = [
      { name: 'base_url', value: 'https://api.example.com', has_value: true },
      { name: 'api_key', value: null, has_value: true },
      { name: 'headers', value: { 'X-Team': 'studio' }, has_value: true },
      { name: 'region', value: 'cn-east', has_value: true },
    ]

    expect(splitConnectionConfig(items)).toEqual({
      fields: {
        baseUrl: 'https://api.example.com',
        apiKey: '',
        headersText: '{\n  "X-Team": "studio"\n}',
      },
      advanced: { region: 'cn-east' },
      hasValueByName: {
        base_url: true,
        api_key: true,
        headers: true,
        region: true,
      },
    })
  })

  it('保存时保留留空的旧密钥并合并高级设置', () => {
    expect(
      buildConnectionConfigItems({
        fields: {
          baseUrl: 'https://api.example.com',
          apiKey: '',
          headersText: '{"X-Team":"studio"}',
        },
        advanced: { region: 'cn-east' },
        hasExistingApiKey: true,
      })
    ).toEqual([
      { name: 'base_url', value: 'https://api.example.com' },
      { name: 'headers', value: { 'X-Team': 'studio' } },
      { name: 'region', value: 'cn-east' },
    ])
  })
})
