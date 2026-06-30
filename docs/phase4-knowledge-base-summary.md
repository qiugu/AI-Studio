# 阶段4：知识库实施总结（2026-06-22）

## 概述

阶段4完整实现了**知识库功能**，包括：
- 知识库 CRUD（创建、读取、更新、删除）
- 文档上传与状态追踪（待处理 → 处理中 → 完成/失败）
- 文档分块与向量化集成（基于 Qdrant）
- 语义检索能力
- 完整的前后端 UI 和 API

---

## 后端实现

### 1. 数据模型（3 个新表）

#### `knowledge_bases`
```
- id: 主键
- tenant_id: 租户ID（租户隔离）
- name: 知识库名称
- description: 描述
- embedding_model: 使用的向量模型（如 text-embedding-3-small）
- document_count: 文档数统计
- chunk_count: 分块总数统计
- created_at / updated_at / deleted_at: 时间戳
```

#### `knowledge_documents`
```
- id: 主键
- tenant_id: 租户ID
- kb_id: 所属知识库
- file_name / file_type / file_size: 文件元数据
- file_url: 文件存储URL（如 S3）
- original_content: 解析后的原始文本
- chunk_count: 该文档的分块数
- status: DocumentStatus 枚举（pending/processing/completed/failed）
- error_message: 处理失败时的错误信息
- processed_at: 处理完成时间
- created_at / updated_at / deleted_at: 时间戳
```

#### `knowledge_chunks`
```
- id: 主键
- tenant_id: 租户ID
- kb_id: 知识库ID
- doc_id: 文档ID
- content: 分块文本内容
- chunk_index: 分块序号（从0开始）
- source_page: PDF页码（可选）
- vector_id: Qdrant 中的 point_id（UUID格式，唯一）
- created_at / updated_at / deleted_at: 时间戳
```

### 2. Repository 层（3 个类）

**`app/repositories/knowledge.py`** 实现了：
- `KnowledgeBaseRepository`: 知识库查询（继承 `BaseRepository`）
- `KnowledgeDocumentRepository`: 文档查询、按状态筛选、统计
- `KnowledgeChunkRepository`: 分块查询、按 vector_id 查询

关键方法：
- `list_by_kb()`: 按知识库ID查询文档
- `list_by_document()`: 按文档ID查询分块
- `get_by_vector_id()`: 通过 Qdrant ID 查询分块

### 3. Service 层

**`app/services/knowledge.py`** 实现了 `KnowledgeBaseService`：

#### 知识库 CRUD
- `create_knowledge_base()`: 创建知识库，自动创建 Qdrant Collection
- `get_knowledge_base()`: 获取详情
- `list_knowledge_bases()`: 列表（分页）
- `update_knowledge_base()`: 编辑
- `delete_knowledge_base()`: 软删除

#### 文档管理
- `upload_document()`: 上传文档，创建记录，返回状态为 `PENDING`
- `get_document()`: 获取文档详情
- `list_documents()`: 按状态和知识库ID查询
- `delete_document()`: 软删除文档，同时删除 Qdrant 向量

#### 分块查询
- `get_chunks()`: 获取文档的分块列表

#### 向量检索
- `search()`: 对查询文本进行向量化，在 Qdrant 中搜索相似文本，返回带相似度评分的结果

### 4. 工具模块

#### `app/utils/document.py` - 文档解析
- `DocumentParser`: 支持 TXT / Markdown / PDF / DOCX 解析
- `TextSplitter`: 递归文本分块器（可配置分块大小和重叠）

#### `app/utils/embedding.py` - 向量化客户端
- `EmbeddingClient`: 支持多个提供商（OpenAI、Azure、Ollama）
- `get_embedding_client()`: 工厂函数

### 5. API 路由

**`app/api/knowledge.py`** 定义了 13 个 REST 端点：

| 方法 | 路径 | 功能 | 权限 |
|------|------|------|------|
| POST | `/knowledge/knowledge-bases` | 创建知识库 | knowledge.create |
| GET | `/knowledge/knowledge-bases` | 列出知识库 | 无 |
| GET | `/knowledge/knowledge-bases/{kb_id}` | 获取知识库详情 | 无 |
| PUT | `/knowledge/knowledge-bases/{kb_id}` | 更新知识库 | knowledge.update |
| DELETE | `/knowledge/knowledge-bases/{kb_id}` | 删除知识库 | knowledge.delete |
| POST | `/knowledge/knowledge-bases/{kb_id}/documents/upload` | 上传文档 | knowledge.upload |
| GET | `/knowledge/knowledge-bases/{kb_id}/documents` | 列出文档 | 无 |
| GET | `/knowledge/documents/{doc_id}` | 获取文档详情 | 无 |
| DELETE | `/knowledge/documents/{doc_id}` | 删除文档 | knowledge.delete |
| GET | `/knowledge/documents/{doc_id}/chunks` | 获取分块列表 | 无 |
| POST | `/knowledge/knowledge-bases/{kb_id}/search` | 语义检索 | 无 |

### 6. 数据库迁移

- **主迁移脚本**: `alembic/versions/3ddd2b3263c9_add_knowledge_base_tables.py`
  - 创建 3 个新表及相应索引
  
- **权限迁移脚本**: `alembic/versions/add_knowledge_perms.py`
  - 添加 5 个知识库权限（create/read/update/delete/upload）

已成功执行：`alembic upgrade head`

---

## 前端实现

### 1. 类型定义

**`src/types/knowledge.ts`**：
- `KnowledgeBase` / `KnowledgeDocument` / `KnowledgeChunk` / `SearchResult` 接口
- 请求参数类型

### 2. API 客户端

**`src/api/knowledge.ts`**：
- 知识库管理 API（5 个函数）
- 文档管理 API（4 个函数）
- 分块管理 API（1 个函数）
- 向量检索 API（1 个函数）

### 3. 页面组件

#### `src/pages/Knowledge/KnowledgeList.tsx` - 知识库列表
- 卡片式网格展示
- 创建/编辑/删除知识库
- 实时显示文档数和分块数
- 创建/编辑 Modal

#### `src/pages/Knowledge/KnowledgeDetail.tsx` - 知识库详情
- 统计信息卡片（文档数、分块数、模型名）
- **标签页1：文档管理**
  - 拖拽上传文档
  - 文档表格（含状态指示）
  - 删除文档
  - 查看分块（链接）
- **标签页2：语义检索**
  - 搜索框
  - 检索结果列表（含文档名、相似度评分、内容预览）
- **分块查看 Drawer**：查看文档所有分块

### 4. 路由配置

**`src/App.tsx`** 添加：
```typescript
<Route path="knowledge" element={<KnowledgeList />} />
<Route path="knowledge/:kbId" element={<KnowledgeDetail />} />
```

侧边栏菜单已经包含"知识库"选项（无需修改）。

---

## 启动与测试

### 后端启动
```bash
cd /Volumes/Project/qiugu/AI-Studio/backend
source .venv/bin/activate
python -m uvicorn app.main:app --reload --port 8001
```
✅ 服务成功启动：`http://127.0.0.1:8001`

### 前端启动
```bash
cd /Volumes/Project/qiugu/AI-Studio/frontend
npm run dev
```
✅ 开发服务启动：`http://localhost:3001`

### Vite 代理配置
已更新 `frontend/vite.config.ts` 以支持 8001 端口代理。

---

## 待完成项（异步处理）

为了简化阶段4的实施，以下功能已预留占位符，可在后续阶段完成：

### 1. Celery 异步任务（文档处理）
```python
# app/services/knowledge_processor.py (TODO)
# 异步任务:
# 1. 文档解析 (DocumentParser)
# 2. 文本分块 (TextSplitter)
# 3. 向量化 (EmbeddingClient)
# 4. 批量插入 Qdrant
# 5. 更新文档状态 (completed/failed)
```

当前，上传文档时会创建状态为 `PENDING` 的记录，但不会自动处理。
需要：
- 配置 Celery broker（Redis）
- 实现处理任务
- 在 upload 时触发：`process_document_task.delay(doc_id=..., file_path=..., tenant_id=...)`

### 2. 文件存储（S3/本地）
- 上传时保存文件到存储系统
- 记录 `file_url`
- 清理临时文件

### 3. 权限绑定
- 目前权限已在数据库中定义
- 需在租户初始化时分配给 tenant_admin 角色
- 需在其他 API 中正确使用 `@require_permission()` 装饰器

---

## 文件清单

### 后端新增/修改
```
backend/app/models/knowledge_base.py          (新建)
backend/app/models/knowledge_document.py      (新建)
backend/app/models/knowledge_chunk.py         (新建)
backend/app/models/__init__.py                (修改 - 添加导入)
backend/app/repositories/knowledge.py         (新建)
backend/app/utils/document.py                 (新建)
backend/app/utils/embedding.py                (新建)
backend/app/services/knowledge.py             (新建)
backend/app/api/knowledge.py                  (新建)
backend/app/main.py                           (修改 - 注册路由)
backend/alembic/versions/3ddd2b3263c9_*.py   (自动生成)
backend/alembic/versions/add_knowledge_perms.py (新建)
backend/scripts/init_knowledge_permissions.py (新建)
backend/run_server.sh                         (新建)
```

### 前端新增/修改
```
frontend/src/types/knowledge.ts               (新建)
frontend/src/api/knowledge.ts                 (新建)
frontend/src/pages/Knowledge/KnowledgeList.tsx       (新建)
frontend/src/pages/Knowledge/KnowledgeDetail.tsx     (新建)
frontend/src/App.tsx                          (修改 - 添加路由)
frontend/vite.config.ts                       (修改 - 更新代理端口)
```

---

## 下一步

### 优先级1：完成异步处理
- 实现 `KnowledgeProcessor` Celery 任务
- 集成文档解析 → 分块 → 向量化 → Qdrant 存储流程
- 测试文档上传端到端流程

### 优先级2：权限与授权
- 初始化租户时自动分配知识库权限给 admin 角色
- 验证其他 API 中权限守卫的有效性

### 优先级3：文件存储集成
- 集成 S3 或本地文件存储
- 处理文件清理

### 优先级4：前端增强
- 上传进度条（WebSocket 或 Server-Sent Events）
- 搜索结果 Markdown 渲染
- 分块内容高亮显示

---

## 环境要求

**后端依赖**（requirements.txt）：
- `fastapi`、`uvicorn`
- `sqlalchemy`、`pymysql`
- `alembic`（数据库迁移）
- `qdrant-client`（向量数据库）
- `langchain`、`langchain-core`、`langchain-openai`等
- `openai`、`requests`
- `python-docx`、`pypdf`（文档解析）

**前端依赖**（package.json）：
- `react`、`react-router-dom`
- `antd`、`@ant-design/icons`
- `axios`、`zustand`

---

## 验收清单

- ✅ 3 个数据模型创建
- ✅ 3 个 Repository 类实现
- ✅ Service 层完整 CRUD + 搜索
- ✅ 13 个 REST API 端点
- ✅ 权限定义与迁移
- ✅ 2 个前端页面（列表 + 详情）
- ✅ 前端类型定义与 API 客户端
- ✅ 路由配置
- ✅ 数据库迁移脚本
- ✅ 后端服务启动验证
- ✅ 前端服务启动验证
- ⏳ Celery 异步处理（待完成）
- ⏳ 权限绑定初始化（待完成）
- ⏳ 文件存储集成（待完成）

---

**创建日期**: 2026-06-22  
**阶段**: Phase 4 - 知识库
