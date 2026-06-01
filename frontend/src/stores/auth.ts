import { create } from 'zustand'
import {
  login as loginApi,
  register as registerApi,
  logout as logoutApi,
  getCurrentUser,
} from '@/api/auth'
import type { User } from '@/types/api'
import { setToken, setRefreshToken, clearAuth, getToken } from '@/utils/auth'

interface AuthState {
  user: User | null
  token: string | null
  loading: boolean
  initializing: boolean
  isLoggedIn: boolean

  login: (email: string, password: string) => Promise<void>
  register: (
    email: string,
    password: string,
    passwordRepeat: string,
    nickname?: string,
  ) => Promise<void>
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

  login: async (email, password) => {
    set({ loading: true })
    try {
      const res = await loginApi({ email, password })
      const { access_token, refresh_token, user } = res.data
      setToken(access_token)
      setRefreshToken(refresh_token)
      set({ user, token: access_token, isLoggedIn: true })
    } catch (err) {
      throw err
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
      // 注册成功后自动登录（后端返回 token + user）
      if (res.data && 'access_token' in res.data) {
        const { access_token, refresh_token, user } =
          res.data as unknown as import('@/types/api').LoginResponse
        setToken(access_token)
        setRefreshToken(refresh_token)
        set({ user, token: access_token, isLoggedIn: true })
      }
    } finally {
      set({ loading: false })
    }
  },

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
