import apiClient from './client'
import type {
  ApiResponse,
  LoginRequest,
  LoginResponse,
  RegisterRequest,
  RegisterResponse,
  RefreshRequest,
  RefreshResponse,
  VerifyEmailResponse,
  ResendVerificationResponse,
  User,
} from '@/types/api'

export async function login(data: LoginRequest): Promise<ApiResponse<LoginResponse>> {
  const response = await apiClient.post('/auth/login', data)
  return response as unknown as ApiResponse<LoginResponse>
}

export async function register(
  data: RegisterRequest,
): Promise<ApiResponse<RegisterResponse>> {
  const response = await apiClient.post('/auth/register', data)
  return response as unknown as ApiResponse<RegisterResponse>
}

/** 使用邮箱验证令牌激活账号；成功后返回令牌，可直接进入系统。 */
export async function verifyEmail(
  token: string,
): Promise<ApiResponse<VerifyEmailResponse>> {
  const response = await apiClient.post('/auth/verify-email', { token })
  return response as unknown as ApiResponse<VerifyEmailResponse>
}

/** 重发验证邮件；开发态（未配置 SMTP）会在 data.verification_token 返回令牌。 */
export async function resendVerification(
  email: string,
): Promise<ApiResponse<ResendVerificationResponse>> {
  const response = await apiClient.post('/auth/resend-verification', { email })
  return response as unknown as ApiResponse<ResendVerificationResponse>
}

export async function refreshToken(data: RefreshRequest): Promise<ApiResponse<RefreshResponse>> {
  const response = await apiClient.post('/auth/refresh', data)
  return response as unknown as ApiResponse<RefreshResponse>
}

export async function logout(): Promise<ApiResponse<null>> {
  const response = await apiClient.post('/auth/logout')
  return response as unknown as ApiResponse<null>
}

export async function getCurrentUser(): Promise<ApiResponse<User>> {
  const response = await apiClient.get('/auth/me')
  return response as unknown as ApiResponse<User>
}
