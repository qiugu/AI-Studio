import { describe, expect, it } from 'vitest'

import {
  containsSensitiveConfig,
  requiresPluginConfigReauth,
  requiresProviderReauth,
  requiresRoleUpdateReauth,
} from './reauth'

describe('reauthentication boundaries', () => {
  it('does not require confirmation for ordinary plugin configuration', () => {
    expect(requiresPluginConfigReauth([{ name: 'base_url', value: 'https://api.example.com' }])).toBe(false)
    expect(requiresPluginConfigReauth([{ name: 'headers', value: { 'X-Team': 'studio' } }])).toBe(false)
  })

  it('requires confirmation for plugin credentials including nested header credentials', () => {
    expect(requiresPluginConfigReauth([{ name: 'api_key', value: 'secret' }])).toBe(true)
    expect(requiresPluginConfigReauth([{ name: 'headers', value: { 'X-Api-Key': 'secret' } }])).toBe(true)
  })

  it('requires provider confirmation only for API keys or sensitive config fields', () => {
    expect(requiresProviderReauth(undefined, { region: 'cn' })).toBe(false)
    expect(requiresProviderReauth(undefined, { api_key: 'secret' })).toBe(true)
    expect(requiresProviderReauth('secret', undefined)).toBe(true)
  })

  it('requires role confirmation only when status changes', () => {
    expect(requiresRoleUpdateReauth(true, true)).toBe(false)
    expect(requiresRoleUpdateReauth(true, false)).toBe(true)
  })

  it('does not treat ordinary nested values as sensitive', () => {
    expect(containsSensitiveConfig({ timeout: 30, region: 'cn' })).toBe(false)
  })
})
