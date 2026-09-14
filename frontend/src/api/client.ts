import axios, { type AxiosInstance, type AxiosResponse } from 'axios'
import { applyAuthInterceptor, setupResponseInterceptor } from '@/utils/request'

const apiClient: AxiosInstance = axios.create({
  baseURL: '/api',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
})

/**
 * AI 类长耗时请求的专用超时（毫秒）。
 *
 * 模型推理（Prompt 测试、供应商/模型连通性检测、工作流执行）常超过默认 30s，
 * 尤其是本地 Ollama 首次调用需加载模型。若沿用默认 30s，浏览器会先于后端返回
 * 而报 "timeout of 30000ms exceeded"（用户看到的就是"超时"）。
 * 此处与生产 nginx `proxy_read_timeout 300s` 对齐，保证前端不会先于网关放弃。
 */
export const AI_REQUEST_TIMEOUT = 300_000

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