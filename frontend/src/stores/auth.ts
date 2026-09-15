import { create } from 'zustand'
import {
  login as loginApi,
  register as registerApi,
  verifyEmail as verifyEmailApi,
  logout as logoutApi,
  getCurrentUser,
} from '@/api/auth'
import type { User, VerifyEmailResponse } from '@/types/api'
import { setToken, setRefreshToken, clearAuth, getToken } from '@/utils/auth'

interface PendingVerification {
  email: string
  devToken: string | null
}

interface AuthState {
  user: User | null
  token: string | null
  loading: boolean
  initializing: boolean
  isLoggedIn: boolean
  /** 注册成功后等待邮箱验证的上下文（开发态可携带验证令牌）。 */
  pendingVerification: PendingVerification | null

  login: (email: string, password: string) => Promise<void>
  register: (
    email: string,
    password: string,
    passwordRepeat: string,
    nickname?: string,
  ) => Promise<void>
  /** 使用验证令牌激活账号并直接登录。 */
  verifyAndLogin: (token: string) => Promise<VerifyEmailResponse>
  /** 清空待验证上下文（离开验证页或验证失败时调用）。 */
  clearPendingVerification: () => void
  logout: () => Promise<void>
  fetchUser: () => Promise<void>
  initialize: () => Promise<void>
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  token: getToken(),
  loading: false,
  initializing: true,
  isLoggedIn: !!getToken(),
  pendingVerification: null,

  login: async (email, password) => {
    set({ loading: true })
    try {
      const res = await loginApi({ email, password })
      const { access_token, refresh_token, user } = res.data
      setToken(access_token)
      setRefreshToken(refresh_token)
      set({ user, token: access_token, isLoggedIn: true })
    } finally {
      set({ loading: false })
    }
  },

  register: async (email, password, passwordRepeat, nickname) => {
    set({ loading: true })
    try {
      const res = await registerApi({
        email,
        password,
        password_repeat: passwordRepeat,
        nickname,
      })
      // 受控自助模式：注册成功后进入邮箱验证流程，不自动登录。
      // 开发态（未配置 SMTP）后端在 verification_token 返回令牌，便于本地直接激活。
      const data = res.data
      set({
        pendingVerification: {
          email,
          devToken: data?.verification_token ?? null,
        },
      })
    } finally {
      set({ loading: false })
    }
  },

  verifyAndLogin: async (token: string) => {
    set({ loading: true })
    try {
      const res = await verifyEmailApi(token)
      const { access_token, refresh_token, user } = res.data
      setToken(access_token)
      setRefreshToken(refresh_token)
      set({
        user,
        token: access_token,
        isLoggedIn: true,
        pendingVerification: null,
      })
      return res.data
    } finally {
      set({ loading: false })
    }
  },

  clearPendingVerification: () => set({ pendingVerification: null }),

  logout: async () => {
    try {
      await logoutApi()
    } catch {
      // ignore
    } finally {
      clearAuth()
      set({ user: null, token: null, isLoggedIn: false })
    }
  },

  fetchUser: async () => {
    try {
      const res = await getCurrentUser()
      set({ user: res.data, isLoggedIn: true })
    } catch {
      clearAuth()
      set({ user: null, token: null, isLoggedIn: false })
    }
  },

  initialize: async () => {
    const token = getToken()
    if (token) {
      try {
        const res = await getCurrentUser()
        set({ user: res.data, isLoggedIn: true, token })
      } catch {
        clearAuth()
        set({ user: null, token: null, isLoggedIn: false })
      }
    }
    set({ initializing: false })
  },
}))
