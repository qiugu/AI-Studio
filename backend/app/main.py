import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.api.auth import router as auth_router
from app.api.ai_provider import router as ai_provider_router
from app.api.ai_model import router as ai_model_router
from app.api.prompt import router as prompt_router
from app.api.knowledge import router as knowledge_router
from app.core.redis import init_redis, redis_close
from app.core.exceptions import AppException
from app.middleware.tenant import TenantMiddleware
from app.middleware.audit import AuditMiddleware
from app.middleware.rate_limit import RateLimitMiddleware

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting AI Studio API server...")
    await init_redis()
    yield
    logger.info("Shutting down AI Studio API server...")
    await redis_close()


app = FastAPI(
    title="AI Studio",
    version="0.1.0",
    description="企业级 AI 应用平台 API",
    lifespan=lifespan,
    openapi_prefix="/api",
    servers=[
        {"url": "/api", "description": "API Gateway"},
    ],
)

# ── 中间件注册顺序（后注册先执行）────────────────────────────────────────────
# 1. CORS（最先处理跨域预检）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 2. 限流（在业务处理前拦截超频请求）
app.add_middleware(RateLimitMiddleware)

# 3. 租户隔离（解析 token 中的 tenant_id 并校验租户状态）
app.add_middleware(TenantMiddleware)

# 4. 审计日志（记录写操作，在业务逻辑执行后记录响应状态）
app.add_middleware(AuditMiddleware)


# ── 全局异常处理器 ────────────────────────────────────────────────────────────
@app.exception_handler(AppException)
async def app_exception_handler(request: Request, exc: AppException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": exc.status_code,
            "message": exc.detail,
            "data": None,
        },
    )


@app.exception_handler(ValidationError)
async def pydantic_validation_exception_handler(request: Request, exc: ValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "code": 422,
            "message": "Validation error",
            "data": exc.errors(),
        },
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception: %s", exc)
    return JSONResponse(
        status_code=500,
        content={
            "code": 500,
            "message": "Internal server error",
            "data": None,
        },
    )


# ── 路由注册 ──────────────────────────────────────────────────────────────────
app.include_router(auth_router, prefix="/auth", tags=["认证"])
app.include_router(ai_provider_router, prefix="/providers", tags=["AI供应商"])
app.include_router(ai_model_router, prefix="/ai-models", tags=["AI模型"])
app.include_router(prompt_router, prefix="/prompts", tags=["Prompt管理"])
app.include_router(knowledge_router, prefix="/knowledge", tags=["知识库"])


@app.get("/health", tags=["系统"])
async def health_check():
    return {"status": "ok", "version": "0.1.0"}
