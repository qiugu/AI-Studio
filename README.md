# AI-Studio

企业级 AI 应用平台，支持多租户、RBAC 权限管理，集成 LLM 调用、知识库、Agent、工作流和插件系统。

## 目录

- [项目简介](#项目简介)
- [技术栈](#技术栈)
- [系统架构](#系统架构)
- [功能模块](#功能模块)
- [快速开始](#快速开始)
- [项目结构](#项目结构)
- [API 文档](#api-文档)
- [开发计划](#开发计划)

## 项目简介

AI-Studio 是一个面向企业的 AI 应用平台，提供以下核心能力：

- **多租户隔离**：基于 `BaseRepository` 租户过滤基类，从数据层根本防止跨租户数据泄漏
- **RBAC 权限管理**：细粒度的资源+操作权限矩阵，支持角色定制
- **AI 模型管理**：统一管理多家 AI 供应商（OpenAI、Anthropic、Azure、Ollama 等），API Key 双层加密存储
- **知识库 (RAG)**：文档上传、解析、分块、向量化，基于 pgvector 语义检索
- **Agent 系统**：LangChain ReAct Agent，支持工具绑定（知识库、API、工作流、插件），SSE 流式对话
- **工作流引擎**：可视化 DAG 编辑器（React Flow），支持 LLM/条件/知识库/代码/工具/循环节点
- **插件系统**：基于 OpenAPI 规范的第三方 API 集成
- **监控审计**：全量审计日志、Token 用量统计、调用监控仪表盘

## 技术栈

### 后端

| 组件 | 技术 |
|------|------|
| Web 框架 | FastAPI + Uvicorn |
| ORM | SQLAlchemy 2.0 |
| 主数据库 | MySQL + PyMySQL |
| 向量数据库 | PostgreSQL + pgvector |
| 缓存/队列 | Redis |
| 异步任务 | Celery |
| LLM 抽象层 | LangChain |
| 认证 | JWT (PyJWT) + passlib/bcrypt |
| API Key 加密 | cryptography (Fernet) |
| 数据库迁移 | Alembic |

### 前端

| 组件 | 技术 |
|------|------|
| 框架 | React 19 + TypeScript |
| 构建工具 | Vite |
| UI 组件库 | Ant Design + @ant-design/x |
| 状态管理 | Zustand |
| 路由 | React Router v7 |
| HTTP 客户端 | Axios |
| 流式响应 | SSE (Server-Sent Events) |

## 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                      Frontend (React + Vite)                │
│  Ant Design · Zustand · React Flow · @ant-design/x         │
└──────────────────────────┬──────────────────────────────────┘
                           │ HTTP / SSE
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                    API Gateway (FastAPI)                     │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐  │
│  │  Auth    │ │ Tenant   │ │  Audit   │ │  Rate Limit  │  │
│  │Middleware│ │Middleware│ │Middleware│ │  Middleware   │  │
│  └──────────┘ └──────────┘ └──────────┘ └──────────────┘  │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                    Service Layer                             │
│  Auth · User · AIModel · Prompt · Knowledge · Agent        │
│  Workflow · Plugin · Audit · Quota · Admin                  │
└──┬───────────────────┬────────────────────┬─────────────────┘
   │                   │                    │
   ▼                   ▼                    ▼
┌───────┐      ┌──────────────┐      ┌──────────┐
│ MySQL │      │ PG + pgvector│      │  Redis   │
│(关系型)│      │  (向量检索)  │      │(缓存/队列)│
└───────┘      └──────────────┘      └──────────┘
```

## 功能模块

### 已实现

- [x] 基础架构：FastAPI 入口、CORS、全局异常处理
- [x] 中间件：租户隔离、审计日志、限流（Redis）
- [x] 认证 API：登录、注册（含租户初始化）、Token 刷新、登出

### 开发中（分阶段实施）

| 阶段 | 模块 | 状态 |
|------|------|------|
| 一 | 基础架构完善（RBAC、中间件、异常体系） | 进行中 |
| 二 | AI 模型管理（供应商、模型 CRUD、LangChain 集成） | 待开始 |
| 三 | Prompt 管理（版本控制、变量渲染、测试运行） | 待开始 |
| 四 | 知识库（文档上传/解析/分块、pgvector 检索） | 待开始 |
| 五 | Agent 系统（ReAct Agent、工具绑定、SSE 流式对话） | 待开始 |
| 六 | 工作流引擎（DAG 执行、React Flow 可视化编辑器） | 待开始 |
| 七 | 插件系统（OpenAPI 解析、插件调用沙盒） | 待开始 |
| 八 | 监控审计（审计日志、Token 统计、Dashboard） | 待开始 |

## 快速开始

### 环境要求

- Python 3.11+
- Node.js 20+
- MySQL 8.0+
- PostgreSQL 15+ (with pgvector extension)
- Redis 7+

### 后端启动

```bash
# 1. 进入后端目录
cd backend

# 2. 创建并激活虚拟环境
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 3. 安装依赖
pip install -r requirements.txt

# 4. 配置环境变量
cp .env.example .env
# 编辑 .env 填写数据库连接信息

# 5. 运行数据库迁移
alembic upgrade head

# 6. 启动开发服务器
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 前端启动

```bash
# 1. 进入前端目录
cd frontend

# 2. 安装依赖
npm install

# 3. 启动开发服务器
npm run dev
```

启动后访问 `http://localhost:5173`，后端 API 文档访问 `http://localhost:8000/docs`。

### 环境变量说明

在 `backend/.env` 中配置以下变量：

```env
# MySQL
DATABASE_HOST=localhost
DATABASE_PORT=3306
DATABASE_NAME=ai_studio
DATABASE_USERNAME=root
DATABASE_PASSWORD=your_password

# PostgreSQL + pgvector
VECTOR_DB_HOST=localhost
VECTOR_DB_PORT=5432
VECTOR_DB_NAME=ai_studio_vector
VECTOR_DB_USERNAME=postgres
VECTOR_DB_PASSWORD=your_password

# Redis
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=

# JWT
JWT_SECRET_KEY=your-secret-key-change-in-production
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=30
JWT_REFRESH_TOKEN_EXPIRE_DAYS=7

# Fernet 加密密钥（用于 API Key 加密存储）
FERNET_KEY=your-fernet-key

# 文件上传
UPLOAD_DIR=/tmp/ai_studio/uploads
MAX_UPLOAD_SIZE_MB=50

# Celery
CELERY_BROKER_URL=redis://localhost:6379/1
CELERY_RESULT_BACKEND=redis://localhost:6379/2
```

## 项目结构

```
AI-Studio/
├── backend/                        # 后端（FastAPI）
│   ├── app/
│   │   ├── main.py                 # 应用入口
│   │   ├── core/
│   │   │   ├── config.py           # 配置管理
│   │   │   ├── database.py         # MySQL 连接
│   │   │   ├── vector_db.py        # pgvector 连接
│   │   │   ├── security.py         # JWT/密码哈希
│   │   │   ├── dependencies.py     # 依赖注入
│   │   │   └── exceptions.py       # 自定义异常
│   │   ├── models/                 # SQLAlchemy ORM 模型
│   │   ├── schemas/                # Pydantic 请求/响应模型
│   │   ├── api/                    # 路由层
│   │   ├── services/               # 业务逻辑层
│   │   ├── repositories/           # 数据访问层（含 BaseRepository）
│   │   ├── middleware/             # 中间件（租户/审计/限流）
│   │   └── utils/                  # 工具函数（LLM/Embedding/加密/文档解析）
│   ├── alembic/                    # 数据库迁移
│   ├── requirements.txt
│   └── alembic.ini
├── frontend/                       # 前端（React + Vite）
│   ├── src/
│   │   ├── api/                    # API 客户端
│   │   ├── components/             # 通用组件
│   │   ├── hooks/                  # 自定义 Hooks
│   │   ├── pages/                  # 页面组件
│   │   ├── stores/                 # Zustand 状态管理
│   │   ├── types/                  # TypeScript 类型定义
│   │   └── utils/                  # 工具函数
│   ├── package.json
│   └── vite.config.ts
└── docs/                           # 设计文档
    ├── architecture.md             # 系统架构设计
    ├── api-design.md               # API 路由设计
    ├── database-design.md          # 数据库设计
    ├── core-mechanisms.md          # 核心机制实现
    ├── frontend-design.md          # 前端设计
    └── implementation-plan.md      # 分阶段实施计划
```

## API 文档

启动后端后访问：

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

主要 API 端点概览：

| 前缀 | 说明 |
|------|------|
| `/api/auth` | 认证（登录、注册、Token 刷新） |
| `/api/users` | 用户管理 |
| `/api/roles` | 角色与权限管理 |
| `/api/tenants` | 租户管理 |
| `/api/ai-providers` | AI 供应商管理 |
| `/api/ai-models` | AI 模型管理 |
| `/api/prompts` | Prompt 管理 |
| `/api/knowledge-bases` | 知识库管理 |
| `/api/agents` | Agent 管理与对话 |
| `/api/workflows` | 工作流管理与执行 |
| `/api/plugins` | 插件管理 |
| `/api/audit` | 审计日志与监控 |
| `/api/admin` | 平台超级管理员接口 |

## 开发计划

详见 [docs/implementation-plan.md](docs/implementation-plan.md)，共 8 个阶段，每阶段后端和前端同步开发，每阶段结束进行 code review 和联调测试。

## 贡献

1. Fork 本仓库
2. 创建 feature 分支：`git checkout -b feature/your-feature`
3. 提交变更：`git commit -m "feat: add your feature"`
4. 推送分支：`git push origin feature/your-feature`
5. 创建 Pull Request

## License

MIT
