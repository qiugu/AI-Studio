# AI-Studio 前端架构设计

## 技术栈

| 技术 | 版本 | 说明 |
|------|------|------|
| React | ^19.0.0 | UI框架 |
| TypeScript | ^5.0.0 | 类型系统 |
| Vite | ^6.0.0 | 构建工具 |
| Ant Design | ^5.0.0 | 组件库 |
| @ant-design/x | ^1.0.0 | AI对话组件 |
| Zustand | ^5.0.0 | 状态管理 |
| React Router | ^7.0.0 | 路由 |
| Axios | ^1.7.0 | HTTP客户端 |
| @xyflow/react | ^12.0.0 | 工作流可视化 |
| react-markdown | ^9.0.0 | Markdown渲染 |
| highlight.js | ^11.0.0 | 代码高亮 |
| dayjs | ^1.11.0 | 日期处理 |

## 目录结构

```
frontend/
├── public/
│   ├── favicon.ico
│   └── assets/
├── src/
│   ├── main.tsx                      # 入口
│   ├── App.tsx                       # 根组件(路由配置)
│   ├── vite-env.d.ts
│   │
│   ├── api/                          # API请求层
│   │   ├── client.ts                # axios实例+请求/响应拦截器
│   │   ├── auth.ts                  # 认证相关API
│   │   ├── user.ts                  # 用户管理API
│   │   ├── role.ts                  # 角色权限API
│   │   ├── ai-model.ts             # AI模型API
│   │   ├── prompt.ts                # Prompt API
│   │   ├── knowledge.ts             # 知识库API
│   │   ├── workflow.ts              # 工作流API
│   │   ├── agent.ts                 # Agent API
│   │   ├── plugin.ts                # 插件API
│   │   └── audit.ts                 # 审计API
│   │
│   ├── stores/                       # Zustand状态管理
│   │   ├── auth.ts                  # 认证状态(token, user, login/logout)
│   │   ├── user.ts                  # 用户管理状态
│   │   └── app.ts                   # 全局状态(侧边栏折叠/主题等)
│   │
│   ├── hooks/                        # 自定义Hooks
│   │   ├── useAuth.ts               # 认证相关钩子
│   │   ├── usePermission.ts         # 权限检查钩子
│   │   ├── usePagination.ts         # 分页钩子
│   │   └── useSSE.ts               # SSE流式响应钩子
│   │
│   ├── components/                   # 通用组件
│   │   ├── Layout/
│   │   │   ├── AppLayout.tsx        # 主布局(侧边栏+头部+内容)
│   │   │   ├── Sidebar.tsx          # 侧边导航
│   │   │   └── Header.tsx           # 顶部栏
│   │   ├── PermissionGuard.tsx      # 权限守卫组件(RBAC)
│   │   ├── AdminGuard.tsx           # 超级管理员路由守卫(检查 is_platform_admin)
│   │   ├── Pagination.tsx           # 通用分页封装
│   │   ├── CodeEditor.tsx           # 代码/Prompt编辑器(Monaco)
│   │   ├── MarkdownRenderer.tsx     # Markdown渲染组件
│   │   ├── ChatMessage.tsx         # 对话消息组件
│   │   ├── ChatInput.tsx           # 对话输入组件
│   │   └── TokenCounter.tsx       # Token计数组件
│   │
│   ├── pages/                        # 页面
│   │   ├── Login/
│   │   │   └── index.tsx            # 登录页
│   │   ├── Dashboard/
│   │   │   └── index.tsx            # 仪表盘(概览)
│   │   ├── AIModels/
│   │   │   ├── ModelList.tsx        # 模型列表
│   │   │   ├── ModelForm.tsx        # 模型创建/编辑表单
│   │   │   ├── ProviderList.tsx     # 供应商列表
│   │   │   └── ProviderForm.tsx     # 供应商表单
│   │   ├── Prompts/
│   │   │   ├── PromptList.tsx       # Prompt列表
│   │   │   ├── PromptDetail.tsx     # Prompt详情+版本管理
│   │   │   └── PromptEditor.tsx    # Prompt编辑器(含变量高亮)
│   │   ├── Knowledge/
│   │   │   ├── KnowledgeList.tsx    # 知识库列表
│   │   │   ├── KnowledgeDetail.tsx # 知识库详情(文档管理)
│   │   │   └── DocumentUpload.tsx  # 文档上传组件
│   │   ├── Workflows/
│   │   │   ├── WorkflowList.tsx     # 工作流列表
│   │   │   ├── WorkflowEditor.tsx   # 可视化流程编辑器(React Flow)
│   │   │   └── WorkflowExecution.tsx # 执行记录详情
│   │   ├── Agents/
│   │   │   ├── AgentList.tsx        # Agent列表
│   │   │   ├── AgentForm.tsx        # Agent创建/编辑
│   │   │   └── AgentChat.tsx        # Agent对话界面(SSE流式)
│   │   ├── Plugins/
│   │   │   ├── PluginList.tsx       # 插件列表
│   │   │   └── PluginConfig.tsx     # 插件配置
│   │   ├── System/
│   │   │   ├── Users.tsx            # 用户管理
│   │   │   ├── Roles.tsx            # 角色权限管理
│   │   │   ├── AuditLogs.tsx        # 审计日志
│   │   │   └── TenantSettings.tsx   # 当前租户设置(信息/成员/配额使用情况)
│   │   ├── Admin/                   # 平台超级管理员专属(is_platform_admin=true)
│   │   │   ├── TenantList.tsx       # 所有租户列表(状态/套餐/用量概览)
│   │   │   └── TenantDetail.tsx     # 租户详情(配额修改/禁用/注销)
│   │   └── Settings/
│   │       └── index.tsx            # 系统设置
│   │
│   ├── types/                        # TypeScript类型定义
│   │   ├── user.ts
│   │   ├── ai-model.ts
│   │   ├── prompt.ts
│   │   ├── knowledge.ts
│   │   ├── workflow.ts
│   │   ├── agent.ts
│   │   ├── plugin.ts
│   │   └── api.ts                   # 通用API响应类型
│   │
│   ├── utils/
│   │   ├── request.ts              # 请求工具函数
│   │   ├── auth.ts                  # Token存取
│   │   ├── permission.ts           # 权限判断工具
│   │   └── constants.ts            # 常量定义
│   │
│   └── styles/
│       └── global.css               # 全局样式+Ant Design主题变量
│
├── index.html
├── vite.config.ts
├── tsconfig.json
├── tsconfig.node.json
├── .eslintrc.cjs
├── .prettierrc
└── package.json
```

## 路由配置

```tsx
// App.tsx 路由结构
<Routes>
  <Route path="/login" element={<Login />} />
  <Route path="/" element={<AppLayout />}>
    <Route index element={<Dashboard />} />
    <Route path="ai-models" element={<ModelList />} />
    <Route path="ai-models/create" element={<ModelForm />} />
    <Route path="ai-models/:id/edit" element={<ModelForm />} />
    <Route path="providers" element={<ProviderList />} />
    <Route path="providers/create" element={<ProviderForm />} />
    <Route path="providers/:id/edit" element={<ProviderForm />} />
    <Route path="prompts" element={<PromptList />} />
    <Route path="prompts/:id" element={<PromptDetail />} />
    <Route path="prompts/:id/edit" element={<PromptEditor />} />
    <Route path="knowledge" element={<KnowledgeList />} />
    <Route path="knowledge/:id" element={<KnowledgeDetail />} />
    <Route path="workflows" element={<WorkflowList />} />
    <Route path="workflows/:id/edit" element={<WorkflowEditor />} />
    <Route path="workflows/:id/executions/:execId" element={<WorkflowExecution />} />
    <Route path="agents" element={<AgentList />} />
    <Route path="agents/:id" element={<AgentForm />} />
    <Route path="agents/:id/chat" element={<AgentChat />} />
    <Route path="plugins" element={<PluginList />} />
    <Route path="plugins/:id/config" element={<PluginConfig />} />
    <Route path="system/users" element={<Users />} />
    <Route path="system/roles" element={<Roles />} />
    <Route path="system/audit-logs" element={<AuditLogs />} />
    <Route path="system/tenant" element={<TenantSettings />} />
    <Route path="settings" element={<Settings />} />
    {/* 平台超级管理员专属路由，AdminGuard 检查 user.is_platform_admin */}
    <Route path="admin" element={<AdminGuard />}>
      <Route path="tenants" element={<TenantList />} />
      <Route path="tenants/:id" element={<TenantDetail />} />
    </Route>
  </Route>
</Routes>
```

## 核心页面设计要点

### 1. Dashboard 仪表盘
- Token用量趋势图(折线图)
- 模型调用统计(柱状图)
- 活跃Agent/工作流数
- 近期审计日志

### 2. AI模型管理
- 供应商卡片式列表(状态指示灯显示连通性)
- 模型表格(类型筛选、供应商筛选)
- 创建/编辑表单(供应商选择、模型参数配置)
- 连通性/调用测试弹窗

### 3. Prompt编辑器
- 左右分栏: 变量列表 | Prompt内容区
- 变量高亮显示({{variable}})
- 版本对比(Diff视图)
- 测试运行面板(输入变量 → 结果展示)

### 4. 知识库
- 列表: 卡片式展示(文档数、分块数、状态)
- 详情: 文档列表 + 上传区
- 文档状态指示(pending → processing → completed/failed)
- 检索测试面板

### 5. 工作流编辑器
- 基于React Flow的可视化拖拽编辑器
- 节点类型面板: LLM、条件、代码、知识库、工具、输入/输出
- 节点配置侧边栏(动态表单)
- 执行面板(输入参数 → SSE流式输出 → 节点执行状态高亮)

### 6. Agent对话
- 基于Ant Design X的聊天界面
- SSE流式响应
- 工具调用展示(折叠面板)
- 对话历史侧边栏
- 上下文引用展示

### 7. 审计日志
- 高级筛选(时间范围、操作类型、资源类型、用户)
- 数据表格(支持导出CSV)
- 详情弹窗

### 8. 租户设置（TenantSettings）
- 当前租户基本信息展示与编辑（名称、描述）
- 成员列表与角色管理
- 配额使用情况（用户数/模型数进度条，含上限提示）

### 9. 平台管理后台（Admin，is_platform_admin 专属）
- **TenantList**: 所有租户列表，状态徽标（启用/禁用）、套餐标签、Token 用量摘要、快速禁用操作
- **TenantDetail**: 租户详情，包含配额修改表单、用量图表、成员数统计、注销租户危险操作区

### AdminGuard 组件说明

```tsx
// src/components/AdminGuard.tsx
// 检查当前登录用户的 is_platform_admin 字段
// 非超级管理员重定向至首页，防止通过 URL 直接访问 /admin/* 路由
const AdminGuard: React.FC = () => {
  const { user } = useAuthStore();
  if (!user?.is_platform_admin) {
    return <Navigate to="/" replace />;
  }
  return <Outlet />;
};
```

## API客户端设计

```tsx
// api/client.ts
const apiClient = axios.create({
  baseURL: '/api',
  timeout: 30000,
});

// 请求拦截: 注入JWT Token
apiClient.interceptors.request.use((config) => {
  const token = getToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// 响应拦截: 统一错误处理
apiClient.interceptors.response.use(
  (response) => response.data,
  (error) => {
    if (error.response?.status === 401) {
      // 跳转登录
    }
    return Promise.reject(error.response?.data);
  }
);
```

## SSE流式 Hook设计

```tsx
// hooks/useSSE.ts
function useSSE(url: string) {
  const [data, setData] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);

  const start = useCallback(async (body: object) => {
    setIsStreaming(true);
    setData('');
    const response = await fetch(`/api${url}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${getToken()}`,
      },
      body: JSON.stringify(body),
    });
    const reader = response.body!.getReader();
    const decoder = new TextDecoder();
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      const chunk = decoder.decode(value, { stream: true });
      // 解析SSE格式
      setData(prev => prev + chunk);
    }
    setIsStreaming(false);
  }, [url]);

  return { data, isStreaming, start };
}
```