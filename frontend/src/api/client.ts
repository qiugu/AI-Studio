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

apiClient.interceptors.response.use(
  (response: AxiosResponse) => response.data,
  (error) => Promise.reject(error),
)

export default apiClient