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
type PendingRequest = {
  config: AuthRequestConfig
  resolve: (value: unknown) => void
  reject: (reason?: unknown) => void
}
// 在 axios 默认请求配置上扩展的自定义字段：
//   _retry              标记该请求是否已用刷新令牌重试过，避免 401 刷新死循环
//   _suppressErrorMessage 是否禁用全局错误提示弹窗
type AuthRequestConfig = InternalAxiosRequestConfig & {
  _retry?: boolean
  _suppressErrorMessage?: boolean
}

let pendingRequests: PendingRequest[] = []

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
      const originalRequest = error.config as AuthRequestConfig

      if (error.response?.status === 401 && !originalRequest._retry) {
        const refreshToken = getRefreshToken()

        if (!refreshToken) {
          clearAuth()
          onRefreshFail?.()
          return Promise.reject(error)
        }

        // 同一次刷新窗口内：排队等待，避免并发刷新（E9：存 resolve/reject，而非单参数回调）
        if (isRefreshing) {
          return new Promise((resolve, reject) => {
            pendingRequests.push({ config: originalRequest, resolve, reject })
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

          // 用新令牌重试本请求与所有排队请求
          pendingRequests.forEach(({ config, resolve }) => {
            config._retry = true
            config.headers.Authorization = `Bearer ${newToken}`
            resolve(axios(config))
          })
          pendingRequests = []

          originalRequest.headers.Authorization = `Bearer ${newToken}`
          return axios(originalRequest)
        } catch (refreshError) {
          // E9：刷新失败必须 reject 所有排队请求，否则它们会永久挂起（Promise 泄漏）
          pendingRequests.forEach(({ reject }) => reject(refreshError))
          pendingRequests = []
          clearAuth()
          onRefreshFail?.()
          return Promise.reject(refreshError)
        } finally {
          isRefreshing = false
        }
      }

      // 对于非 401 错误，检查是否需要弹出全局错误提示
      // 如果请求配置了 _suppressErrorMessage，则不弹出错误消息
      if (error.response?.status !== 401 && !originalRequest._suppressErrorMessage) {
        const msg = getErrorMessage(error)
        message.error(msg)
      }

      return Promise.reject(error)
    },
  )
}