import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { useEffect } from 'react'
import { useAuthStore } from '@/stores/auth'
import AppLayout from '@/components/Layout/AppLayout'
import Login from '@/pages/Login'
import VerifyEmail from '@/pages/Login/VerifyEmail'
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
import TenantDetail from '@/pages/Admin/TenantDetail'
import AdminGuard from '@/components/AdminGuard'
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
              path="/verify-email"
              element={
                <GuestRoute>
                  <VerifyEmail />
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
              {/* Phase 3: Prompt 管理 */}
              <Route path="prompts" element={<PromptList />} />
              <Route path="prompts/new" element={<PromptEditor />} />
              <Route path="prompts/:id/edit" element={<PromptEditor />} />
              <Route path="prompts/:id" element={<PromptDetail />} />
              {/* Phase 4: 知识库 */}
              <Route path="knowledge" element={<KnowledgeList />} />
              <Route path="knowledge/:kbId" element={<KnowledgeDetail />} />
              {/* Phase 5: Agent */}
              <Route path="agents" element={<AgentList />} />
              <Route path="agents/create" element={<AgentForm />} />
              <Route path="agents/:agentId/edit" element={<AgentForm />} />
              <Route path="agents/:agentId/chat" element={<AgentChat />} />
              {/* Phase 6: Workflow */}
              <Route path="workflows" element={<WorkflowList />} />
              <Route path="workflows/create" element={<WorkflowForm />} />
              <Route path="workflows/:workflowId" element={<WorkflowEditor />} />
              <Route path="workflows/:workflowId/edit" element={<WorkflowEditor />} />
              <Route path="workflows/:workflowId/execute" element={<WorkflowExecution />} />
              {/* Phase 7: 插件系统 */}
              <Route path="plugins" element={<PluginList />} />
              <Route path="plugins/:id/config" element={<PluginConfig />} />
              {/* Phase 8: 监控审计 & 系统管理 */}
              <Route path="system/users" element={<Users />} />
              <Route path="system/roles" element={<Roles />} />
              <Route path="system/audit-logs" element={<AuditLogs />} />
              <Route path="system/tenant" element={<TenantSettings />} />
              {/* Phase 8: 平台管理（仅超级管理员） */}
              <Route
                path="admin/tenants"
                element={
                  <AdminGuard>
                    <TenantList />
                  </AdminGuard>
                }
              />
              <Route
                path="admin/tenants/:id"
                element={
                  <AdminGuard>
                    <TenantDetail />
                  </AdminGuard>
                }
              />
            </Route>
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </AppInitializer>
      </BrowserRouter>
    </ConfigProvider>
  )
}