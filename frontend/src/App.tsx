import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { appTheme } from '@/theme'
import { useEffect } from 'react'
import { useAuthStore } from '@/stores/auth'
import AppLayout from '@/components/Layout/AppLayout'
import Login from '@/pages/Login'
import VerifyEmail from '@/pages/Login/VerifyEmail'
import ResetPassword from '@/pages/Login/ResetPassword'
import Dashboard from '@/pages/Dashboard'
import ProviderList from '@/pages/AIModels/ProviderList'
import ProviderForm from '@/pages/AIModels/ProviderForm'
import ModelList from '@/pages/AIModels/ModelList'
import ModelForm from '@/pages/AIModels/ModelForm'
import PromptList from '@/pages/Prompts/PromptList'
import PromptEditor from '@/pages/Prompts/PromptEditor'
import PromptDetail from '@/pages/Prompts/PromptDetail'
import KnowledgeList from '@/pages/Knowledge/KnowledgeList'
import KnowledgeDetail from '@/pages/Knowledge/KnowledgeDetail'
import AgentList from '@/pages/Agents/AgentList'
import AgentForm from '@/pages/Agents/AgentForm'
import AgentChat from '@/pages/Agents/AgentChat'
import WorkflowList from '@/pages/Workflows/WorkflowList'
import WorkflowForm from '@/pages/Workflows/WorkflowForm'
import WorkflowEditor from '@/pages/Workflows/WorkflowEditor'
import WorkflowExecution from '@/pages/Workflows/WorkflowExecution'
import PluginList from '@/pages/Plugins/PluginList'
import PluginConfig from '@/pages/Plugins/PluginConfig'
import Users from '@/pages/System/Users'
import Roles from '@/pages/System/Roles'
import AuditLogs from '@/pages/System/AuditLogs'
import TenantSettings from '@/pages/System/TenantSettings'
import TenantList from '@/pages/Admin/TenantList'
import AdminGuard from '@/components/AdminGuard'
import TenantAdminGuard from '@/components/TenantAdminGuard'
import TenantUserGuard from '@/components/TenantUserGuard'
import { canManageSystem } from '@/utils/permission'
import './styles/global.css'

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
    <ConfigProvider locale={zhCN} theme={appTheme}>
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
              path="/verify-email"
              element={
                <GuestRoute>
                  <VerifyEmail />
                </GuestRoute>
              }
            />
            <Route path="/reset-password" element={<ResetPassword />} />
            <Route
              path="/"
              element={
                <AuthRoute>
                  <TenantUserGuard>
                    <AppLayout />
                  </TenantUserGuard>
                </AuthRoute>
              }
            >
              <Route index element={<TenantHome />} />
              {/* Phase 2: AI 模型管理 */}
              <Route path="providers" element={<TenantAdminGuard><ProviderList /></TenantAdminGuard>} />
              <Route path="providers/new" element={<TenantAdminGuard><ProviderForm /></TenantAdminGuard>} />
              <Route path="providers/:id/edit" element={<TenantAdminGuard><ProviderForm /></TenantAdminGuard>} />
              <Route path="ai-models" element={<TenantAdminGuard><ModelList /></TenantAdminGuard>} />
              <Route path="ai-models/new" element={<TenantAdminGuard><ModelForm /></TenantAdminGuard>} />
              <Route path="ai-models/:id/edit" element={<TenantAdminGuard><ModelForm /></TenantAdminGuard>} />
              {/* Phase 3: Prompt 管理 */}
              <Route path="prompts" element={<TenantAdminGuard><PromptList /></TenantAdminGuard>} />
              <Route path="prompts/new" element={<TenantAdminGuard><PromptEditor /></TenantAdminGuard>} />
              <Route path="prompts/:id/edit" element={<TenantAdminGuard><PromptEditor /></TenantAdminGuard>} />
              <Route path="prompts/:id" element={<TenantAdminGuard><PromptDetail /></TenantAdminGuard>} />
              {/* Phase 4: 知识库 */}
              <Route path="knowledge" element={<KnowledgeList />} />
              <Route path="knowledge/:kbId" element={<KnowledgeDetail />} />
              {/* Phase 5: Agent */}
              <Route path="agents" element={<AgentList />} />
              <Route path="agents/create" element={<TenantAdminGuard><AgentForm /></TenantAdminGuard>} />
              <Route path="agents/:agentId/edit" element={<TenantAdminGuard><AgentForm /></TenantAdminGuard>} />
              <Route path="agents/:agentId/chat" element={<AgentChat />} />
              {/* Phase 6: Workflow */}
              <Route path="workflows" element={<WorkflowList />} />
              <Route path="workflows/create" element={<TenantAdminGuard><WorkflowForm /></TenantAdminGuard>} />
              <Route path="workflows/:workflowId" element={<TenantAdminGuard><WorkflowEditor /></TenantAdminGuard>} />
              <Route path="workflows/:workflowId/edit" element={<TenantAdminGuard><WorkflowEditor /></TenantAdminGuard>} />
              <Route path="workflows/:workflowId/execute" element={<WorkflowExecution />} />
              {/* Phase 7: 插件系统 */}
              <Route path="plugins" element={<TenantAdminGuard><PluginList /></TenantAdminGuard>} />
              <Route path="plugins/:id/config" element={<TenantAdminGuard><PluginConfig /></TenantAdminGuard>} />
              {/* Phase 8: 监控审计 & 系统管理 */}
              <Route path="system/users" element={<TenantAdminGuard><Users /></TenantAdminGuard>} />
              <Route path="system/roles" element={<TenantAdminGuard><Roles /></TenantAdminGuard>} />
              <Route path="system/audit-logs" element={<TenantAdminGuard><AuditLogs /></TenantAdminGuard>} />
              <Route path="system/tenant" element={<TenantAdminGuard><TenantSettings /></TenantAdminGuard>} />
            </Route>
            {/* 平台管理员只进入租户创建页面，不进入租户业务工作区。 */}
            <Route
              path="/admin/tenants"
              element={
                <AuthRoute>
                  <AdminGuard>
                    <AppLayout />
                  </AdminGuard>
                </AuthRoute>
              }
            >
              <Route index element={<TenantList />} />
            </Route>
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </AppInitializer>
      </BrowserRouter>
    </ConfigProvider>
  )
}

function TenantHome() {
  const user = useAuthStore((s) => s.user)
  if (canManageSystem(user)) return <Dashboard />
  return <Navigate to="/agents" replace />
}
