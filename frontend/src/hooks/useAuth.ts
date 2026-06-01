import { useAuthStore } from '@/stores/auth'

export function useAuth() {
  const { user, token, loading, isLoggedIn, login, logout, fetchUser } = useAuthStore()

  return {
    user,
    token,
    loading,
    isLoggedIn,
    login,
    logout,
    fetchUser,
  }
}