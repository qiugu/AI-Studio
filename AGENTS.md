# AGENTS.md

技术架构与开发指南。本文档面向**开发者与 AI 编码代理**，聚焦系统架构、技术栈、项目结构、运行部署等工程信息。

> **文档分工**
> - 本文档（AGENTS.md）：系统架构、技术栈、项目结构、运行/部署、API 概览。
> - [CLAUDE.md](CLAUDE.md)：编码约定（多租户隔离、BaseRepository、异常体系、SSE 规范等），修改代码前必读。
> - [docs/](docs/)：设计文档（系统架构、API 设计、数据库设计、核心机制、前端设计、实施计划）。
> - [README.md](README.md)：业务功能与价值定位（面向使用者/决策者）。

---

## 项目概述

AI-Studio 是前后端分离的企业级 AI 应用平台：

- **后端**：Python + FastAPI，位于 `backend/`
- **前端**：React + TypeScript + Vite，位于 `frontend/`
- **设计文档**：位于 `docs/`

> 核心业务 ID 已统一为字符串 UUID v4，数据库层以 `varchar(36)` 存储，后端模型、Alembic 迁移与前端接口/页面调用已同步适配。

---

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

---

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
│ MySQL │      │ Qdrant       │      │  Redis   │
│(关系型)│      │  (向量检索)  │      │(缓存/队列)│
└───────┘      └──────────────┘      └──────────┘
```

---

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
│   │   │   ├── vector_db.py        # Qdrant 连接
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

---

## 关键技术约定（摘要）

完整编码约定见 [CLAUDE.md](CLAUDE.md)。要点：

- **多租户隔离**：租户过滤由 `core/tenant_scope.py` 全局过滤器在 ORM 执行期强制注入（不可绕过）；`BaseRepository` 仅用于 conversation / knowledge / workflow / agent 等复用场景。Service 层可直接使用注入的 `Session` 做简单查询，含平台公共行（`tenant_id IS NULL`）的可见性须统一调用 `public_or_tenant_filter(...)`，禁止手写租户过滤条件。详见 `CLAUDE.md`「多租户数据隔离」。
- **主键规范**：核心业务 ID 为字符串 UUID v4，模型定义为 `String(36)`。
- **统一响应**：`{ "code": 0, "message": "success", "data": {} }`。
- **异常处理**：使用 `app/core/exceptions.py` 自定义异常，禁止直接抛 `HTTPException`。
- **配额检查**：创建受限资源前先调用 `QuotaService`。
- **SSE 规范**：标准 `event: message\ndata: {...}\n\n` 格式，JSON 序列化 `ensure_ascii=False`，`media_type="text/event-stream"`。
- **权限守卫**：路由使用 `require_permission`，超级管理员接口使用 `require_platform_admin`。

新增 API 端点的标准步骤：模型 → Schema → Repository → Service（含配额）→ 路由（含守卫）→ 注册 → Alembic 迁移。

---

## 运行与开发

### 环境要求

- Python 3.11+
- Node.js 20+
- MySQL 8.0+ / Qdrant / Redis 7+

### 后端

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # 编辑填写数据库连接等信息
alembic upgrade head          # 数据库迁移
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 前端

```bash
cd frontend
npm install
npm run dev                   # 开发：http://localhost:5173
npm run build                 # 生产构建
npm run lint                  # ESLint 检查
```

### 健康检查

```bash
curl http://localhost:8000/health
```

### 环境变量

`backend/.env` 常用变量（以 `backend/app/core/config.py` 与 `backend/.env.example` 为准）：

```env
DATABASE_HOST / DATABASE_PORT / DATABASE_NAME / DATABASE_USERNAME / DATABASE_PASSWORD
QDRANT_URL / QDRANT_API_KEY
REDIS_HOST / REDIS_PORT / REDIS_PASSWORD
JWT_SECRET_KEY / JWT_ALGORITHM / JWT_ACCESS_TOKEN_EXPIRE_MINUTES / JWT_REFRESH_TOKEN_EXPIRE_DAYS
FERNET_KEY                      # API Key 加密；生成：python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
UPLOAD_DIR / MAX_UPLOAD_SIZE_MB
CELERY_BROKER_URL / CELERY_RESULT_BACKEND
EMBEDDING_PROVIDER / EMBEDDING_MODEL / EMBEDDING_API_KEY / EMBEDDING_API_BASE
OLLAMA_BASE_URL
```

---

## Docker 一键部署

```bash
cd AI-Studio
cp .env.example .env          # 必改：MYSQL_ROOT_PASSWORD / MYSQL_PASSWORD / JWT_SECRET_KEY / FERNET_KEY
docker compose up -d --build
docker compose ps
```

| 服务 | 地址 |
|------|------|
| 前端控制台 | http://localhost:80 |
| Swagger API 文档 | http://localhost:8000/docs |
| Qdrant 管理面板 | http://localhost:6333/dashboard |

常用运维命令：

```bash
docker compose logs -f backend                 # 后端日志
docker compose down                            # 停止（保留数据卷）
docker compose down -v                         # 停止并删除数据卷（清空数据库！）
git pull && docker compose up -d --build       # 更新后重建
```

> Docker 部署使用项目根目录 `.env`，与本地开发的 `backend/.env` 是两套独立配置。数据持久化于 Docker 命名卷，`docker compose down` 不删数据，仅 `-v` 会清空。

---

## API 端点概览

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

启动后端后在线文档：`http://localhost:8000/docs`（Swagger）、`http://localhost:8000/redoc`（ReDoc）。

---

## 参考文档

- [CLAUDE.md](CLAUDE.md) — 编码约定
- [README.md](README.md) — 业务功能
- [docs/architecture.md](docs/architecture.md) — 系统架构设计
- [docs/api-design.md](docs/api-design.md) — API 路由设计
- [docs/database-design.md](docs/database-design.md) — 数据库设计
- [docs/core-mechanisms.md](docs/core-mechanisms.md) — 核心机制实现
- [docs/frontend-design.md](docs/frontend-design.md) — 前端设计
- [docs/implementation-plan.md](docs/implementation-plan.md) — 分阶段实施计划
