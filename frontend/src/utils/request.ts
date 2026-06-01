import axios, { type AxiosError, type AxiosInstance, type InternalAxiosRequestConfig, type AxiosResponse } from 'axios'
import { getToken, getRefreshToken, setToken, clearAuth } from './auth'
import { message } from 'antd'

export function applyAuthInterceptor(config: InternalAxiosRequestConfig) {
  const token = getToken()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
}

let isRefreshing = false
let pendingRequests: Array<(token: string) => void> = []

/**
 * 从 AxiosError 中提取后端返回的 message 字段。
 * 后端统一格式：{ code, message, data }
 */
export function getErrorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const backendMsg = (error.response?.data as { message?: string })?.message
    if (backendMsg) return backendMsg
  }
  if (error instanceof Error) return error.message
  return '请求失败'
}

export function setupResponseInterceptor(instance: AxiosInstance, onRefreshFail?: () => void) {
  instance.interceptors.response.use(
    (response: AxiosResponse) => response,
    async (error: AxiosError) => {
      const originalRequest = error.config as InternalAxiosRequestConfig & { _retry?: boolean }

      if (error.response?.status === 401 && !originalRequest._retry) {
        const refreshToken = getRefreshToken()

        if (!refreshToken) {
          clearAuth()
          onRefreshFail?.()
          return Promise.reject(error)
        }

        if (isRefreshing) {
          return new Promise((resolve) => {
            pendingRequests.push((token: string) => {
              originalRequest.headers.Authorization = `Bearer ${token}`
              resolve(axios(originalRequest))
            })
          })
        }

        originalRequest._retry = true
        isRefreshing = true

        try {
          const response = await axios.post('/api/auth/refresh', {
            refresh_token: refreshToken,
          })
          const newToken = response.data.data.access_token
          setToken(newToken)

          pendingRequests.forEach((cb) => cb(newToken))
          pendingRequests = []

          originalRequest.headers.Authorization = `Bearer ${newToken}`
          return axios(originalRequest)
        } catch {
          clearAuth()
          onRefreshFail?.()
          return Promise.reject(error)
        } finally {
          isRefreshing = false
        }
      }

      // 对于非 401 错误，统一弹出后端错误提示
      // 401 错误（token 过期/无效）由上方 refresh 逻辑处理，不在此弹窗
      if (error.response?.status !== 401) {
        const msg = getErrorMessage(error)
        message.error(msg)
      }

      return Promise.reject(error)
    },
  )
}