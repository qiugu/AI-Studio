# AI-Studio

企业级 AI 应用平台，支持多租户、RBAC 权限管理，集成 LLM 调用、知识库、Agent、工作流和插件系统。

## 目录

- [项目简介](#项目简介)
- [技术栈](#技术栈)
- [系统架构](#系统架构)
- [功能模块](#功能模块)
- [快速开始](#快速开始)
- [Docker 一键部署](#docker-一键部署)
- [项目结构](#项目结构)
- [API 文档](#api-文档)
- [开发计划](#开发计划)

## 项目简介

AI-Studio 是一个面向企业的 AI 应用平台，提供以下核心能力：

- **多租户隔离**：基于 `BaseRepository` 租户过滤基类，从数据层根本防止跨租户数据泄漏
- **统一主键规范**：所有核心实体的业务 ID 已统一为字符串 UUID v4，并持久化为 `varchar(36)`，前后端接口与页面调用已同步适配
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
| 向量数据库 | Qdrant |
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

### 最近更新

- 已将后端模型、Alembic 迁移和前端类型/接口调用统一切换为字符串 UUID（`varchar(36)`）方案
- 已完成相关数据库迁移，当前主键与外键字段在 MySQL 中以字符串 UUID 形式落库
- 前端页面已同步移除对数字 ID 的强依赖，避免 `Number()` / `parseInt()` 引入的兼容问题

### 已实现

- [x] 基础架构：FastAPI 入口、CORS、全局异常处理
- [x] 中间件：租户隔离、审计日志、限流（Redis）
- [x] 认证 API：登录、注册（含租户初始化）、Token 刷新、登出
- [x] RBAC 权限管理：基于角色的访问控制，细粒度权限矩阵
- [x] AI 模型管理：供应商和模型 CRUD，LangChain 集成，连通性测试
- [x] Prompt 管理：版本控制、变量渲染、测试运行
- [x] 知识库：文档上传/解析/分块、Qdrant 向量检索
- [x] Agent 系统：ReAct Agent、工具绑定、SSE 流式对话、Markdown 渲染

### 开发中（分阶段实施）

| 阶段 | 模块 | 状态 |
|------|------|------|
| 一 | 基础架构完善（RBAC、中间件、异常体系） | 已完成 |
| 二 | AI 模型管理（供应商、模型 CRUD、LangChain 集成） | 已完成 |
| 三 | Prompt 管理（版本控制、变量渲染、测试运行） | 已完成 |
| 四 | 知识库（文档上传/解析/分块、Qdrant 检索） | 已完成 |
| 五 | Agent 系统（ReAct Agent、工具绑定、SSE 流式对话） | 已完成 |
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

# 向量数据库 (Qdrant)
QDRANT_URL=http://localhost:6333
QDRANT_API_KEY=

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

# Embedding 向量化
EMBEDDING_PROVIDER=openai
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_API_KEY=
EMBEDDING_API_BASE=

# Ollama 本地模型
OLLAMA_BASE_URL=http://localhost:11434
```

> 注：以上为常用变量。完整且权威的变量列表以 `backend/app/core/config.py` 为准，
> 可直接参考 `backend/.env.example`（与 `config.py` 字段一一对应）。

## Docker 一键部署

推荐使用 Docker Compose 一键部署，一条命令拉起全部依赖与前后端服务（MySQL、Redis、Qdrant、后端 API、Celery Worker、前端 Nginx）。

### 前置条件

- Docker Engine 20.10+（含 Docker Compose v2）

### 部署步骤

```bash
# 1. 进入项目根目录
cd AI-Studio

# 2. 复制环境变量模板并按需修改
cp .env.example .env
# 必改项：MYSQL_ROOT_PASSWORD / MYSQL_PASSWORD / JWT_SECRET_KEY / FERNET_KEY
# FERNET_KEY 生成：python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# 3. 构建并启动（首次构建需数分钟）
docker compose up -d --build

# 4. 查看服务状态
docker compose ps
```

### 访问入口

| 服务 | 地址 |
|------|------|
| 前端控制台 | http://localhost:80 |
| Swagger API 文档 | http://localhost:8000/docs |
| Qdrant 管理面板 | http://localhost:6333/dashboard |

首次使用：打开前端 → 注册账号（自动初始化租户）→ 在「AI 模型管理」中配置模型供应商与 API Key。

### 常用运维命令

```bash
docker compose logs -f backend                    # 查看后端日志
docker compose down                               # 停止（保留数据卷）
docker compose down -v                            # 停止并删除数据卷（会清空数据库！）
git pull && docker compose up -d --build          # 更新代码后重新构建
```

### 数据持久化

数据（MySQL、Redis、Qdrant、上传文件）保存在 Docker 命名卷中：`docker compose down` 不会删除数据，仅 `docker compose down -v` 会清空。

### 生产注意事项

- 务必修改 `.env` 中的全部密码与密钥，并妥善保管 `FERNET_KEY`（丢失后已加密的 AI 供应商 API Key 将无法解密）
- 前端默认仅暴露 80 端口；如需关闭后端 8000 / Qdrant 6333 对外端口，删除 `docker-compose.yml` 中对应 `ports` 段即可
- 若宿主机 80 端口被占用，可在 `.env` 中修改 `FRONTEND_PORT`
- Docker 部署使用项目根目录的 `.env`，与本地开发的 `backend/.env` 是两套独立配置，互不影响

## 项目结构

```
AI-Studio/
├── docker-compose.yml               # Docker Compose 一键部署编排
├── .env.example                     # Docker Compose 环境变量模板
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
│   ├── Dockerfile                  # 后端镜像（API / Celery Worker 共用）
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
│   ├── Dockerfile                  # 前端镜像（Node 构建 + Nginx）
│   ├── nginx.conf                  # 生产 Nginx 配置（API 反向代理 / SSE）
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
