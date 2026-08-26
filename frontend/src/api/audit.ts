import apiClient from './client'
import type { ApiResponse, PaginatedData, PageParams } from '@/types/api'
import type {
  AuditLog,
  ModelCallLog,
  TokenStats,
  DashboardStats,
} from '@/types/api'

export async function listAuditLogs(
  params?: PageParams & {
    user_id?: string
    action?: string
    resource?: string
    status_code?: number
    start_time?: string
    end_time?: string
  }
): Promise<ApiResponse<PaginatedData<AuditLog>>> {
  const response = await apiClient.get('/audit/logs', { params })
  return response as unknown as ApiResponse<PaginatedData<AuditLog>>
}

export async function listModelCalls(
  params?: PageParams & {
    user_id?: string
    agent_id?: string
    model_id?: string
    status?: string
    start_time?: string
    end_time?: string
  }
): Promise<ApiResponse<PaginatedData<ModelCallLog>>> {
  const response = await apiClient.get('/audit/model-calls', { params })
  return response as unknown as ApiResponse<PaginatedData<ModelCallLog>>
}

export async function getTokenStats(
  params?: { days?: number; agent_id?: string; user_id?: string; model_id?: string }
): Promise<ApiResponse<TokenStats>> {
  const response = await apiClient.get('/audit/token-stats', { params })
  return response as unknown as ApiResponse<TokenStats>
}

export async function getDashboard(): Promise<ApiResponse<DashboardStats>> {
  const response = await apiClient.get('/audit/dashboard')
  return response as unknown as ApiResponse<DashboardStats>
}
