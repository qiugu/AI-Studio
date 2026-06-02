import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { useEffect } from 'react'
import { useAuthStore } from '@/stores/auth'
import AppLayout from '@/components/Layout/AppLayout'
import Login from '@/pages/Login'
import Dashboard from '@/pages/Dashboard'
import ProviderList from '@/pages/AIModels/ProviderList'
import ProviderForm from '@/pages/AIModels/ProviderForm'
import ModelList from '@/pages/AIModels/ModelList'
import ModelForm from '@/pages/AIModels/ModelForm'

function AuthRoute({ children }: { children: React.ReactNode }) {
  const isLoggedIn = useAuthStore((s) => s.isLoggedIn)
  if (!isLoggedIn) {
    return <Navigate to="/login" replace />
  }
  return <>{children}</>
}

function GuestRoute({ children }: { children: React.ReactNode }) {
  const isLoggedIn = useAuthStore((s) => s.isLoggedIn)
  if (isLoggedIn) {
    return <Navigate to="/" replace />
  }
  return <>{children}</>
}

function AppInitializer({ children }: { children: React.ReactNode }) {
  const initialize = useAuthStore((s) => s.initialize)
  const initializing = useAuthStore((s) => s.initializing)

  useEffect(() => {
    initialize()
  }, [initialize])

  if (initializing) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh' }}>
        Loading...
      </div>
    )
  }

  return <>{children}</>
}

export default function App() {
  return (
    <ConfigProvider locale={zhCN}>
      <BrowserRouter>
        <AppInitializer>
          <Routes>
            <Route
              path="/login"
              element={
                <GuestRoute>
                  <Login />
                </GuestRoute>
              }
            />
            <Route
              path="/"
              element={
                <AuthRoute>
                  <AppLayout />
                </AuthRoute>
              }
            >
              <Route index element={<Dashboard />} />
              {/* Phase 2: AI 模型管理 */}
              <Route path="providers" element={<ProviderList />} />
              <Route path="providers/new" element={<ProviderForm />} />
              <Route path="providers/:id/edit" element={<ProviderForm />} />
              <Route path="ai-models" element={<ModelList />} />
              <Route path="ai-models/new" element={<ModelForm />} />
              <Route path="ai-models/:id/edit" element={<ModelForm />} />
            </Route>
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </AppInitializer>
      </BrowserRouter>
    </ConfigProvider>
  )
}