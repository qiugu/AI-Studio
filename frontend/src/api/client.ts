import axios, { type AxiosInstance, type AxiosResponse } from 'axios'
import { applyAuthInterceptor, setupResponseInterceptor } from '@/utils/request'

const apiClient: AxiosInstance = axios.create({
  baseURL: '/api',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
})

apiClient.interceptors.request.use(applyAuthInterceptor)

setupResponseInterceptor(apiClient, () => {
  window.location.href = '/login'
})

// 拦截器返回response.data，实际返回类型是T而非AxiosResponse<T>
// 这里需要类型断言来让TypeScript正确理解
apiClient.interceptors.response.use(
  (response: AxiosResponse) => response.data as any,
  (error) => Promise.reject(error),
)

export default apiClient