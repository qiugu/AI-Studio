# AI-Studio 企业级AI应用平台 — 整体架构设计

## 技术栈

| 层级 | 技术 | 说明 |
|------|------|------|
| 后端框架 | FastAPI + SQLAlchemy | 异步高性能，已有基础 |
| 主数据库 | MySQL | 关系型数据存储 |
| 向量数据库 | Qdrant | 独立部署，专用于向量检索，HNSW索引，原生多租户 payload 过滤 |
| 缓存/队列 | Redis | 缓存 + 限流 + Celery Broker |
| 异步任务 | Celery | 文档处理等CPU密集型任务 |
| LLM抽象层 | LangChain | 统一多模型调用 |
| 前端框架 | React + Vite + TypeScript | |
| UI组件库 | Ant Design | 企业级管理平台 |
| 状态管理 | Zustand | 轻量级状态管理 |
| 流式响应 | SSE (Server-Sent Events) | LLM流式输出 |

## 系统架构图

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
│  │ Middleware│ │Middleware│ │Middleware│ │  Middleware   │  │
│  └──────────┘ └──────────┘ └──────────┘ └──────────────┘  │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                    Service Layer                             │
│  ┌─────────┐ ┌──────┐ ┌────────┐ ┌────────┐ ┌──────────┐ │
│  │  Auth   │ │User  │ │ AI     │ │ Prompt │ │Knowledge │ │
│  │ Service │ │Svc   │ │Model Svc│ │Service │ │ Service  │ │
│  └─────────┘ └──────┘ └────────┘ └────────┘ └──────────┘ │
│  ┌──────────┐ ┌──────────┐ ┌────────┐ ┌──────────────┐   │
│  │Workflow  │ │  Agent   │ │ Plugin │ │    Audit     │   │
│  │ Engine   │ │ Service  │ │ Service│ │   Service    │   │
│  └──────────┘ └──────────┘ └────────┘ └──────────────┘   │
│  ┌──────────┐ ┌──────────────────────────────────────┐   │
│  │  Quota   │ │            Admin Service              │   │
│  │ Service  │ │  (跨租户管理，仅 is_platform_admin)    │   │
│  └──────────┘ └──────────────────────────────────────┘   │
└──┬───────────────────┬────────────────────┬───────────────┘
   │                   │                    │
   ▼                   ▼                    ▼
┌───────┐      ┌──────────────┐      ┌──────────┐
│ MySQL │      │   Qdrant     │      │  Redis   │
│(关系型)│      │  (向量检索)   │      │(缓存/队列)│
└───────┘      └──────────────┘      └──────────┘
```

## 后端目录结构

```
backend/
├── app/
│   ├── __init__.py
│   ├── main.py                         # FastAPI 入口
│   ├── core/
│   │   ├── config.py                   # 配置(扩展)
│   │   ├── database.py                 # MySQL引擎(完善)
│   │   ├── vector_db.py               # Qdrant客户端管理
│   │   ├── security.py                # JWT/密码哈希/RBAC
│   │   ├── dependencies.py            # 通用Depends
│   │   ├── exceptions.py              # 自定义异常体系
│   │   └── events.py                  # 应用启动/关闭事件
│   ├── models/                         # SQLAlchemy ORM
│   ├── schemas/                        # Pydantic 请求/响应模型
│   ├── api/                            # API路由层
│   ├── services/                       # 业务逻辑层
│   ├── middleware/
│   │   ├── tenant.py                  # 租户隔离中间件
│   │   ├── audit.py                   # 审计日志中间件
│   │   └── rate_limit.py             # 限流中间件
│   ├── repositories/
│   │   └── base.py                    # BaseRepository(租户隔离基类)
│   └── utils/
│       ├── llm.py                     # LangChain LLM客户端封装
│       ├── embedding.py              # Embedding客户端封装
│       ├── encryption.py             # API Key加密工具
│       └── document.py               # 文档解析(docx/pdf/txt/md)
├── alembic/
├── alembic.ini
├── .env
├── requirements.txt
└── Dockerfile
```

## 关键技术决策

| 决策点 | 方案 | 原因 |
|--------|------|------|
| 主数据库 | MySQL (保留) | 已有基础，团队熟悉 |
| 向量数据库 | Qdrant (独立) | HNSW索引，原生多租户payload过滤，无需pgvector扩展 |
| 异步任务 | Celery + Redis | 文档处理/向量化是CPU密集型 |
| 流式响应 | SSE (Server-Sent Events) | LLM流式输出的标准方案 |
| 工作流可视化 | @xyflow/react (React Flow) | 成熟开源流程图库 |
| LLM抽象 | LangChain | 多供应商支持，丰富工具生态 |
| 密码安全 | passlib + bcrypt | 工业级密码哈希 |
| API密钥加密 | cryptography (Fernet) | 双层加密存储LLM API Key |
| 文档解析 | python-docx/pypdf2/bs4 | 覆盖主流文档格式 |
| 租户数据隔离 | BaseRepository 基类自动注入 tenant_id | 防止开发者遗漏过滤条件导致跨租户数据泄漏 |
| 超级管理员 | users.is_platform_admin + require_platform_admin 守卫 | 与普通 RBAC 体系分离，不占用角色权限表，支持跨租户运营 |
| 配额管理 | QuotaService Service 层软检查 | 在业务层创建资源前校验，超出配额返回 429 |

## 依赖清单

### 后端新增依赖

```
# 认证与安全
passlib[bcrypt]==1.7.4
cryptography==44.0.0

# Web
python-multipart==0.0.20
sse-starlette==2.2.1

# 缓存与队列
redis==5.2.1
fastapi-cache2==0.2.2
celery==5.4.0

# 文档解析
python-docx==1.1.2
pypdf2==3.0.1
beautifulsoup4==4.13.3

# LangChain
langchain==0.3.21
langchain-openai==0.3.11
langchain-anthropic==0.3.1
langchain-community==0.3.20
langchain-experimental==0.3.4

# 向量数据库
qdrant-client==1.14.2
```

### 前端核心依赖

```json
{
  "dependencies": {
    "react": "^19.0.0",
    "react-dom": "^19.0.0",
    "react-router-dom": "^7.0.0",
    "antd": "^5.0.0",
    "@ant-design/icons": "^5.0.0",
    "@ant-design/x": "^1.0.0",
    "zustand": "^5.0.0",
    "axios": "^1.7.0",
    "dayjs": "^1.11.0",
    "@xyflow/react": "^12.0.0",
    "react-markdown": "^9.0.0",
    "highlight.js": "^11.0.0"
  },
  "devDependencies": {
    "typescript": "^5.0.0",
    "vite": "^6.0.0",
    "@vitejs/plugin-react": "^4.0.0",
    "eslint": "^9.0.0",
    "@types/react": "^19.0.0"
  }
}
```