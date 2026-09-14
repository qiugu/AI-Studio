import apiClient from './client'
import type { ApiResponse, PaginatedData, PageParams } from '@/types/api'
import type {
  Plugin,
  PluginCreateRequest,
  PluginUpdateRequest,
  PluginEndpoint,
  PluginEndpointCreateRequest,
  PluginEndpointUpdateRequest,
  PluginConfigResponse,
  PluginConfigItem,
  PluginTestRequest,
  PluginTestResult,
} from '@/types/plugin'

// ── 插件 CRUD ──────────────────────────────────────────────────────────────

export async function listPlugins(
  params?: PageParams & {
    include_public?: boolean
    plugin_type?: string
    source_type?: string
    status?: string
  }
): Promise<ApiResponse<PaginatedData<Plugin>>> {
  const response = await apiClient.get('/plugins', { params })
  return response as unknown as ApiResponse<PaginatedData<Plugin>>
}

export async function getPlugin(id: string): Promise<ApiResponse<Plugin>> {
  const response = await apiClient.get(`/plugins/${id}`)
  return response as unknown as ApiResponse<Plugin>
}

export async function createPlugin(
  data: PluginCreateRequest
): Promise<ApiResponse<Plugin>> {
  const response = await apiClient.post('/plugins', data)
  return response as unknown as ApiResponse<Plugin>
}

export async function updatePlugin(
  id: string,
  data: PluginUpdateRequest
): Promise<ApiResponse<Plugin>> {
  const response = await apiClient.put(`/plugins/${id}`, data)
  return response as unknown as ApiResponse<Plugin>
}

export async function deletePlugin(id: string): Promise<ApiResponse<null>> {
  const response = await apiClient.delete(`/plugins/${id}`)
  return response as unknown as ApiResponse<null>
}

export async function testPlugin(
  id: string,
  data?: PluginTestRequest
): Promise<ApiResponse<PluginTestResult>> {
  const response = await apiClient.post(`/plugins/${id}/test`, data ?? {})
  return response as unknown as ApiResponse<PluginTestResult>
}

// ── 端点管理 ──────────────────────────────────────────────────────────────

export async function listEndpoints(
  pluginId: string
): Promise<ApiResponse<PluginEndpoint[]>> {
  const response = await apiClient.get(`/plugins/${pluginId}/endpoints`)
  return response as unknown as ApiResponse<PluginEndpoint[]>
}

export async function addEndpoint(
  pluginId: string,
  data: PluginEndpointCreateRequest
): Promise<ApiResponse<PluginEndpoint>> {
  const response = await apiClient.post(`/plugins/${pluginId}/endpoints`, data)
  return response as unknown as ApiResponse<PluginEndpoint>
}

export async function updateEndpoint(
  pluginId: string,
  endpointId: string,
  data: PluginEndpointUpdateRequest
): Promise<ApiResponse<PluginEndpoint>> {
  const response = await apiClient.put(
    `/plugins/${pluginId}/endpoints/${endpointId}`,
    data
  )
  return response as unknown as ApiResponse<PluginEndpoint>
}

export async function deleteEndpoint(
  pluginId: string,
  endpointId: string
): Promise<ApiResponse<null>> {
  const response = await apiClient.delete(
    `/plugins/${pluginId}/endpoints/${endpointId}`
  )
  return response as unknown as ApiResponse<null>
}

export async function importEndpoints(
  pluginId: string
): Promise<ApiResponse<{ imported: number }>> {
  const response = await apiClient.post(`/plugins/${pluginId}/endpoints/import`)
  return response as unknown as ApiResponse<{ imported: number }>
}

// ── 租户配置 ──────────────────────────────────────────────────────────────

export async function getPluginConfig(
  pluginId: string
): Promise<ApiResponse<PluginConfigResponse>> {
  const response = await apiClient.get(`/plugins/${pluginId}/config`)
  return response as unknown as ApiResponse<PluginConfigResponse>
}

export async function updatePluginConfig(
  pluginId: string,
  items: PluginConfigItem[]
): Promise<ApiResponse<PluginConfigResponse>> {
  const response = await apiClient.put(`/plugins/${pluginId}/config`, {
    items,
  })
  return response as unknown as ApiResponse<PluginConfigResponse>
}
