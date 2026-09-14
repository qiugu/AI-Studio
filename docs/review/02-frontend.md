# 02 · 前端评审（请求层 / 类型安全 / 构建 / 组件质量）

> 范围：`frontend/src`（React 19 + TypeScript + Vite + Ant Design 6 + Zustand + React Router v7 + Axios）
> 规模：78 个 `.ts`/`.tsx` 源文件，合计约 11,727 行（含 CSS）；最大单文件 `pages/Plugins/PluginConfig.tsx` 744 行

---

## 结论

前端的**工程基线明显强于后端**：`tsconfig` 已开启 `noUnusedLocals`/`noUnusedParameters`/`verbatimModuleSyntax`/`noFallthroughCasesInSwitch`，`any` 与 `@ts-ignore` 使用极其克制（全库约 15 处），已配置 ESLint flat config、Prettier、路径别名、Vite 代理与生产 Nginx（含 SSE 关闭缓冲）。流式响应的跨分片缓冲处理（`utils/streamRequest.ts:88-130`）写得相当扎实。

问题集中在四个方面：

1. **两个不可忽视的缺陷**：Markdown 渲染启用 `rehype-raw` 但未做 sanitize（XSS 风险面）；令牌刷新失败时排队请求永久挂起。
2. **类型严格度未拉满**：`strict` 未开启，`strictNullChecks` 缺席使类型系统只能拦截约一半的常见错误。
3. **无任何测试**，且存在两处死代码。
4. **可维护性欠账**：30+ 页面全量静态导入、无错误边界、约 89 处 antd 静态 `message` 调用、API 层普遍使用双重断言。

---

## 一、缺陷与风险

### F1 · Markdown 渲染启用 `rehype-raw` 但未 sanitize（P0）

**位置**：`frontend/src/components/MarkdownRenderer.tsx:24-26`

```tsx
<ReactMarkdown
  remarkPlugins={[remarkGfm]}
  rehypePlugins={[rehypeHighlight, rehypeRaw]}   // ← rehypeRaw 解析原始 HTML
  ...
>
```

**被渲染的内容来源（均为非完全可信输入）**：

| 调用点 | 内容来源 | 可信度 |
|--------|----------|--------|
| `components/Chat/MessageBubble.tsx:76` | 大模型输出 | 可被提示注入影响 |
| `components/Chat/AgentInfo.tsx:51` | `agent.system_prompt` | 租户内用户可自由编辑 |
| `pages/Prompts/PromptDetail.tsx` 等 | Prompt 正文 | 用户可编辑 |
| 知识库文档解析结果 | 上传文档内容 | 外部文件 |

**问题**：`rehype-raw` 会把 Markdown 中的原始 HTML 解析进 HAST 树并渲染为真实 DOM 节点。`react-markdown` 自 v7 起**移除了内置 sanitize**，其官方文档明确要求在渲染不可信内容时**必须**配合 `rehype-sanitize`。本项目 `package.json` 中**未安装** `rehype-sanitize`（已确认检索无命中）。

**严重度定级依据**：具体可利用性取决于 payload 构造方式与 React 对 HTML 属性/节点的处理细节 —— 但这是**明确不应存在的风险面**，且它与 S6 形成叠加：一旦脚本能在已登录会话中执行，存于 `localStorage` 的访问与刷新令牌即可被完整读出，构成从"内容注入"到"账号接管"的完整链路。

**改进建议**（二选一）：
- **方案 A（推荐，副作用最小）**：接入 `rehype-sanitize`，采用默认 schema 并仅在必要时放宽（例如允许 `className` 以保留代码高亮）。注意插件顺序必须是 `[rehypeRaw, rehypeSanitize, rehypeHighlight]`，即 sanitize 必须在 raw **之后**、highlight **之前**。
- **方案 B**：移除 `rehype-raw`，放弃原始 HTML 支持。若业务上无实际需求，这是最彻底的方案（README 中未见对 HTML 渲染能力的宣传）。

**验收标准**：以含 `<img src=x onerror=alert(1)>`、`<script>alert(1)</script>` 的 Markdown 内容渲染，不产生任何脚本执行；正常 Markdown（表格、代码块高亮、链接）渲染效果不变。

---

### S6 · 令牌存储于 `localStorage`（P0）

**位置**：`frontend/src/utils/auth.ts`

```ts
const TOKEN_KEY = 'ai_studio_access_token'
const REFRESH_TOKEN_KEY = 'ai_studio_refresh_token'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}
```

**问题**：访问令牌与刷新令牌均存于 `localStorage`，任何同源脚本（含第三方依赖被投毒、F1 的注入路径）均可读取。刷新令牌尤其敏感 —— 它是长期凭据，泄露后即使访问令牌过期仍可续期。

**改进建议**：
1. 迁移到 `HttpOnly` + `Secure` + `SameSite=Lax/Strict` 的 Cookie 会话，前端不再持有任何令牌。
2. 若因 `Authorization` 头架构（后端 `get_current_user` 依赖该头）暂不迁移，则**至少**：
   - 缩短访问令牌有效期（当前 `core/config.py:46` 默认 5 分钟，实际部署经 Compose 注入为 30 分钟，需统一）；
   - **优先修复 F1**，因为 F1 是使 `localStorage` 方案失效的直接前置条件；
   - 补充 CSP（`Content-Security-Policy`，禁止 `unsafe-inline`）作为纵深防御。
3. 注意：**S6 与后端 [S1](01-backend.md) 强耦合**。若迁移到 Cookie 会话而未同时收敛 CORS 白名单，会直接引入可利用的 CSRF。两者必须同批次整改。

**验收标准**：DevTools 中 `localStorage` 不再出现任何令牌；登录、刷新、登出、多标签页场景全部正常；若采用 Cookie，`HttpOnly` 标志已生效。

---

### E9 · 令牌刷新失败导致排队请求永久挂起（P1）

**位置**：`frontend/src/utils/request.ts:36-42, 58-92`

```ts
let isRefreshing = false
let pendingRequests: Array<(token: string) => void> = []

if (isRefreshing) {
  return new Promise((resolve) => {
    pendingRequests.push((token: string) => {
      originalRequest.headers.Authorization = `Bearer ${token}`
      resolve(axios(originalRequest))
    })
  })
}
...
try {
  const response = await axios.post('/api/auth/refresh', { refresh_token: refreshToken })
  ...
  pendingRequests.forEach((cb) => cb(newToken))
  pendingRequests = []
  originalRequest.headers.Authorization = `Bearer ${newToken}`
  return axios(originalRequest)
} catch {
  clearAuth()
  onRefreshFail?.()
  return Promise.reject(error)     // ← 只 reject 了"发起刷新的那一个"请求
} finally {
  isRefreshing = false
}
```

**问题**：`catch` 分支只 reject 了触发刷新的那个请求。此前被推入 `pendingRequests` 的请求 —— 它们的 `Promise` 只在回调被调用时才 `resolve` —— 在刷新失败后**既不会被 `resolve` 也不会被 `reject`**，其 `Promise` 永久处于 pending 状态。

**影响**：
- 页面上处于等待状态的请求永不结束，`loading` 状态无法复位，用户看到永久转圈。
- 由于 `onRefreshFail` 会跳转 `/login`，多数情况下页面会被重载而掩盖症状；但在**不触发跳转**的路径（例如多个并发请求中已有一个成功刷新）或 SPA 内组件级等待场景下，会表现为难以复现的卡死。
- 属内存与句柄泄漏：pending 的 Promise 及其闭包（含 `originalRequest`）无法被回收。

**改进建议**：将队列从"仅成功回调"改为"成功/失败双通道"，刷新失败时统一 reject：

```ts
// 失败分支中，在 clearAuth() 之前
pendingRequests.forEach((cb) => cb(newToken))       // 成功时
// 失败时
pendingRequests.length = 0                           // 清空并统一 reject
```

推荐做法是维护 `pendingRequests: Array<{ resolve, reject }>`，失败时遍历 `reject(error)` 并清空数组；同时用 `finally` 保证 `isRefreshing` 复位（当前已正确）。

**验收标准**：模拟刷新接口返回 401/500，此前排队的请求全部进入各自的 `catch` 分支；页面无永久 `loading`；`pendingRequests` 在成功与失败两条路径上都被清空。

---

### F2 · SSE 令牌经 URL 查询串传递（P1）

**位置**：`frontend/src/hooks/useSSE.ts:39-45`

```ts
const token = getToken()
if (!token) { setError('No token found'); return }
const urlWithToken = `${url}?token=${token}`      // ← 令牌出现在 URL 中
const eventSource = new EventSource(urlWithToken)
```

**问题**：将 JWT 放入 URL 查询串会使其进入三类持久化载体：Nginx/代理的访问日志、浏览器历史记录、以及跨站请求的 `Referer` 头。这属于 OWASP Cheat Sheet 中明确列为反模式的凭据传递方式（`EventSource` 无法自定义请求头，这是其历史局限，但不应以 URL 传令牌作为折中）。

**重要限定**：该实现目前**是死代码** —— 全库检索显示 `useSSE` 仅有定义、**无任何调用点**；实际流式对话走的是 `pages/Agents/AgentChat.tsx:161` 的 `createStreamRequest`（`utils/streamRequest.ts:34`），该实现使用 `fetch` + `Authorization` 头 + `ReadableStream`，方式正确。

**改进建议**：
1. **删除** `hooks/useSSE.ts`（连同 `createBlockingRequest`，同为死代码），避免后续被误用。
2. 若未来确需 `EventSource`，改用短期一次性票据（ticket）换取连接，或统一使用 `fetch` + `ReadableStream`（现有实现已证明可行）。
3. 同时排查服务端：确认后端是否会记录查询串中的令牌（`middleware/audit.py` 的日志字段需确认不含完整 URL）。

**验收标准**：`hooks/useSSE.ts` 移除后应用功能不变；全库不再出现 `?token=` 形式的凭据传递。

---

### F3 · 死代码：`useSSE` 与 `createBlockingRequest`（P2）

**位置**：`frontend/src/hooks/useSSE.ts`（全文 130 行）、`frontend/src/utils/streamRequest.ts:171`

**事实**：全库检索确认二者**仅有定义、无调用点**。`hooks/useSSE.ts` 承载了上面 F2 的不安全模式。

**建议**：直接删除。理由：死代码会被后来者当作"参考实现"复制，从而扩散不安全模式（这正是 F2 的传播风险）。

**验收标准**：删除后 `tsc -b` 与 `npm run build` 通过。

---

### E9b · 静态 `message` 调用脱离主题上下文（P2）

**位置**：全库约 **89 处** `message.success/error/warning(...)` 静态调用，代表文件：`pages/System/Users.tsx`（5 处）、`pages/Plugins/PluginConfig.tsx`（9 处）、`pages/Knowledge/KnowledgeDetail.tsx`（9 处）、`pages/Workflows/WorkflowEditor.tsx`（7 处）。

**问题**：`App.tsx` 使用了 `<ConfigProvider locale={zhCN}>`，但 antd 的**静态方法**（`message.xxx`）不在 React 上下文树内，无法读取 `ConfigProvider` 提供的主题令牌与全局配置。antd 官方推荐在需要上下文感知的场景使用 `App.useApp()` 或 `message.useMessage()`。

**影响**：主题定制（暗色模式、品牌色、圆角）不会作用于提示消息；若后续引入 `ConfigProvider` 的 `theme` 定制，会出现"页面变了、提示没变"的不一致。

**建议**：在 `App.tsx` 中包裹 `<App>` 组件（antd 6 的 `App` 组件提供 `useApp()`），将静态调用改为 hook 形式。**注意**：这是 89 处调用点的机械替换，应在测试基线建立后进行，避免引入静默行为差异。

**验收标准**：`ConfigProvider` 的 `theme` 变更能一致地作用于提示消息；全局检索静态 `message.` 调用数下降为 0。

---

## 二、类型安全

### E5 · 未开启 `strict`（P2）

**位置**：`frontend/tsconfig.app.json`

已开启项（值得肯定）：`noUnusedLocals`、`noUnusedParameters`、`verbatimModuleSyntax`、`moduleDetection`、`noFallthroughCasesInSwitch`、`erasableSyntaxOnly`。

**缺失项**：`strict: true` 未设置，因此以下子项全部为 `false`：
`strictNullChecks`、`strictFunctionTypes`、`strictBindCallApply`、`strictPropertyInitialization`、`noImplicitThis`、`alwaysStrict`、`useUnknownInCatchVariables`。

**影响评估**（客观说明，不夸大）：`noImplicitAny` 通过 `noUnusedLocals` 的缺失**并未**被覆盖，因此隐式 `any` 仍被允许。但由于代码中显式 `any` 极少（全库约 15 处），且 `noUnusedLocals` 已开启，实际错误拦截能力的损失主要集中在 **`strictNullChecks`**：`null`/`undefined` 可被赋给任意类型，`obj?.x` 式的空值链路不会被静态发现。这是运行时 `Cannot read property of undefined` 类错误的主要来源。

**改进建议（渐进式，遵循 TypeScript Handbook 的迁移路径）**：
1. 第一步：仅开启 `strictNullChecks`（收益最大，噪音可控），修复其暴露的问题。
2. 第二步：开启 `noImplicitThis`、`alwaysStrict`、`useUnknownInCatchVariables`。
3. 第三步：`"strict": true` 全量开启。
4. 每一步都在 CI 中先以报告模式运行（不阻断），待问题清零后再改为阻断。

**验收标准**：`tsc -b` 在 `strict: true` 下通过；CI 中类型检查为阻断项。

---

### E10 · API 层双重断言绕过类型系统（P2）

**位置**：`frontend/src/api/*.ts`，例如 `api/prompt.ts:18-21`

```ts
export async function listPrompts(params?): Promise<ApiResponse<PaginatedData<Prompt>>> {
  const response = await apiClient.get('/prompts', { params })
  return response as unknown as ApiResponse<PaginatedData<Prompt>>
}
```

**根因**：`api/client.ts:20-26` 注册了第二个响应拦截器 `(response) => response.data as any`，把 `AxiosInstance` 的返回类型从 `AxiosResponse<T>` 悄然改成了 `T`，破坏了 axios 的类型契约。类型系统因此无法推断，只能靠 `as unknown as` 双重断言"强行对齐"。

**影响**：`as unknown as` 会**关闭**该赋值处的全部类型检查 —— 后端契约变更（字段改名、层级调整）不会在前端产生任何编译错误，只会在运行时表现为 `undefined`。

**改进建议**（二选一）：
- **方案 A（推荐）**：为 axios 声明模块增强，使 `AxiosInstance` 的 `get/post` 返回 `Promise<T>`，从而移除所有 `as unknown as`，恢复真实类型检查。
- **方案 B**：保留拦截器，但为 `apiClient` 定义显式包装函数（如 `get<T>(url): Promise<ApiResponse<T>>`），在包装层集中做一次类型转换，业务代码不再出现断言。

**配套**：后端 [C1](01-backend.md) 修复后错误响应结构统一，可进一步引入 **Spectral** 对 OpenAPI 描述做契约校验，并将前端类型从 OpenAPI 自动生成，彻底消除手工维护的重复类型（当前 `types/` 下 8 个文件为手写）。

**验收标准**：`grep -rn "as unknown as" frontend/src/api/` 为 0；改动后端某响应字段名后，前端 `tsc -b` 能报错。

---

### 其他类型观察

| 观察 | 位置 | 说明 |
|------|------|------|
| `any` 与抑制注释使用克制 | 全库约 15 处 | 优于多数同规模项目，无需专项治理 |
| `types/` 为手写、与后端契约无自动同步机制 | `frontend/src/types/` 8 个文件 | 长期易漂移，建议由 OpenAPI 生成 |
| `import()` 内联类型断言 | `stores/auth.ts:63` `res.data as unknown as import('@/types/api').LoginResponse` | 同上，属双重断言的另一处表现 |

---

## 三、构建与性能

### E7 · 无路由级代码分割与错误边界（P2）

**位置**：`frontend/src/App.tsx`

**事实**：
- 全部 30+ 个页面组件使用**静态 import**（`App.tsx:8-33`）；
- 全库检索 `React.lazy` / `lazy(` / `Suspense` **零命中**；
- 全库检索 `ErrorBoundary` **零命中**。

**影响**：
1. **首屏体积**：访客即使只访问登录页，也会加载 `@monaco-editor/react`（代码编辑器，体积可观）、`reactflow`（工作流画布）等重量级依赖的全部代码。
2. **容错**：任一页面组件抛错会导致整棵组件树卸载，用户看到白屏且无法通过导航恢复。React 官方文档明确建议在路由层级设置 Error Boundary。

**改进建议**：
1. 页面改为 `const Login = lazy(() => import('@/pages/Login'))`，并在 `<Routes>` 外层包裹 `<Suspense fallback={...}>`。
2. **优先分割重量级依赖所在页面**（Workflows 的编辑器、Plugins 的配置页、CodeEditor 相关页面），收益最明显。
3. 在 `AppLayout` 的 `<Outlet>` 外层增加 Error Boundary，提供"重试/返回首页"入口。
4. 在 `vite.config.ts` 中配置 `build.rollupOptions.output.manualChunks`，将 `reactflow`、`monaco`、`antd` 拆为独立 chunk。
5. 补充 `build.chunkSizeWarningLimit` 并按实际告警调整。

**验收标准**：构建产物中 `monaco`、`reactflow` 不再出现在主入口 chunk；访问登录页时网络面板不加载上述依赖；人为在子页面抛错时显示错误界面而非白屏。

---

### 其他构建观察

| 观察 | 位置 | 说明 |
|------|------|------|
| `vite.config.ts` 无生产构建优化配置 | `vite.config.ts` | 无 `manualChunks`、无 `chunkSizeWarningLimit`、无构建分析插件（如 `rollup-plugin-visualizer`） |
| 存在两套并存的 CSS 方案 | `tailwind.config.js`、`postcss.config.js`、`@tailwindcss/vite`、各页面 `.css` | Tailwind 4 经 Vite 插件接入时通常不再需要 `postcss.config.js` 与 `tailwind.config.js`；需确认是否为遗留配置（`MarkdownRenderer.css`、`AgentChat.css` 等 4 个 CSS 文件合计约 1,400 行，与 Tailwind 的职责存在重叠） |
| 已正确配置开发代理与生产反代 | `vite.config.ts:15-22`、`frontend/nginx.conf` | 开发代理 `/api` → `localhost:8000`；生产 Nginx 已设置 `proxy_buffering off`（SSE 必需）、`proxy_read_timeout 300s`、SPA fallback、静态资源长缓存 —— 这部分做得规范 |
| 容器以 root 运行 | `frontend/Dockerfile` | 详见 [03](03-engineering.md) |

---

## 四、组件与状态质量

### 状态管理

**现状**：Zustand 仅 2 个 store —— `stores/auth.ts`（鉴权）与 `stores/app.ts`（547 字节，全局 UI 态）。**服务端数据全部由页面组件自行用 `useState` + `useEffect` 拉取**，未引入任何服务端状态库（TanStack Query / SWR）。

**评价**：当前规模（30+ 页面）下这是可接受的取舍，且避免了过早引入复杂度。但已出现典型症状：

- 每个列表页都手写一遍 `loading` / `error` / 分页 / 刷新逻辑（`hooks/usePagination.ts` 仅解决了分页部分）；
- 跨页面共享同一份数据时无法自动复用与失效，需手动重新拉取；
- 竞态与重复请求无统一治理。

**建议**：当页面数继续增长或出现"同一数据在多页面需要保持一致"的需求时，引入 TanStack Query 收口服务端状态。**现在不必做**，但建议在文档中记录该决策点与触发条件。

### 组件层观察

| 观察 | 位置 | 说明 |
|------|------|------|
| 最大单文件 744 行 | `pages/Plugins/PluginConfig.tsx` | 含端点表格、配置表单、JSON 校验、导入等职责，建议拆分；`pages/Knowledge/KnowledgeDetail.tsx`（379 行）、`pages/Plugins/PluginList.tsx`（415 行）同类 |
| 样式文件偏大且与组件同名分离 | `pages/Agents/AgentChat.css`（580 行）、`pages/Workflows/WorkflowEditor.css`（442 行） | 760 行页面配 580 行 CSS，建议评估收敛到 CSS Module 或 Tailwind 原子类 |
| 已有可复用的守卫组件 | `components/AdminGuard.tsx`、`components/PermissionGuard.tsx`、`components/Pagination.tsx`、`components/Charts.tsx` | 规划良好，但需确认 `PermissionGuard` 在 4 个缺权限校验的后端模块对应页面上是否已使用（后端 [S2](01-backend.md) 说明前端展示层与后端强制层需一致） |
| 空值/错误态处理不统一 | 各列表页 | 普遍有 `message.error` 提示，但部分页面缺少显式的空态与重试入口 |

---

## 五、前端问题优先级汇总

| ID | 严重度 | 问题 | 一句话理由 |
|----|--------|------|-----------|
| F1 | P0 | `rehype-raw` 未 sanitize | 内容注入风险面，与令牌存储叠加可致账号接管 |
| S6 | P0 | 令牌存于 `localStorage` | XSS 可直接窃取长期凭据；与后端 CORS 需同批整改 |
| E9 | P1 | 刷新失败致请求永久挂起 | 难以复现的卡死与泄漏，修复成本低 |
| F2 | P1 | SSE 令牌经 URL 传递（当前为死代码） | 凭据进入日志/历史/Referer；应删除以阻断扩散 |
| F3 | P2 | `useSSE` 与 `createBlockingRequest` 死代码 | 会被误当参考实现复制 |
| E9b | P2 | 约 89 处 antd 静态 `message` 调用 | 脱离 `ConfigProvider` 主题上下文 |
| E5 | P2 | 未开启 `strict`（缺 `strictNullChecks`） | 空值类运行时错误的主要来源 |
| E10 | P2 | API 层双重断言 | 后端契约变更不产生编译错误 |
| E7 | P2 | 无代码分割与错误边界 | 首屏加载重量级依赖；子页面抛错白屏 |
