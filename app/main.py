import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.api.auth import router as auth_router
from app.api.ai_provider import router as ai_provider_router
from app.api.ai_model import router as ai_model_router
from app.api.prompt import router as prompt_router
from app.api.knowledge import router as knowledge_router
from app.api.agent import router as agent_router
from app.api.workflow import router as workflow_router
from app.api.audit import router as audit_router
from app.api.user import router as user_router
from app.api.role import router as role_router
from app.api.system import router as system_router
from app.api.admin import router as admin_router
from app.api.plugin import router as plugin_router
from app.core.redis import init_redis, redis_close
from app.core.exceptions import AppException, build_error_envelope
from app.core.config import config
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
    servers=[
        {"url": "/api", "description": "API Gateway"},
    ],
)

# ── 中间件注册顺序（后注册先执行）────────────────────────────────────────────
# 1. CORS（最先处理跨域预检）
# 来源白名单由配置 CORS_ORIGINS 驱动（逗号分隔）；为空则拒绝任何跨域，
# 且仅在显式配置了具体源时才允许携带凭证，避免 ``*`` + 凭证的泄露风险（S1）。
_cors_origins = config.cors_origins_list
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=bool(_cors_origins),
    allow_methods=["*"],
    allow_headers=["*"],
)

# 2. 限流（在业务处理前拦截超频请求）
app.add_middleware(RateLimitMiddleware)

# 3. 租户隔离（解析 token 中的 tenant_id 并校验租户状态）
app.add_middleware(TenantMiddleware)

# 4. 审计日志（记录写操作，在业务逻辑执行后记录响应状态）
app.add_middleware(AuditMiddleware)


# 5. 安全响应头（纵深防御，配合前端 Markdown sanitize 降低 XSS 影响面，S6）
@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    # script-src 不含 unsafe-inline，阻断 markdown 注入的内联脚本执行；
    # 若前端构建后续需内联脚本，应改为 nonce 方案而非放宽此处。
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:; font-src 'self' data:; object-src 'none'; "
        "base-uri 'self'; frame-ancestors 'none'",
    )
    return response


# ── 全局异常处理器 ────────────────────────────────────────────────────────────
@app.exception_handler(AppException)
async def app_exception_handler(request: Request, exc: AppException):
    # C2：统一信封，AppException 派生类会携带 error_code 业务码。
    return JSONResponse(status_code=exc.status_code, content=build_error_envelope(exc))


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    # C1/C2：统一信封。裸 ``raise HTTPException`` 也返回 {code, message, data}，
    # 与 AppException 处理器的输出结构保持一致（普通 HTTPException 无 error_code）。
    # 业务异常仍应优先使用 ``app.core.exceptions.AppException`` 以携带 error_code。
    return JSONResponse(status_code=exc.status_code, content=build_error_envelope(exc))


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
app.include_router(agent_router, prefix="/agent", tags=["Agent"])
app.include_router(workflow_router, prefix="/workflows", tags=["工作流"])
app.include_router(user_router, prefix="/users", tags=["用户管理"])
app.include_router(role_router, prefix="/roles", tags=["角色权限"])
app.include_router(system_router, prefix="/system", tags=["系统设置"])
app.include_router(audit_router, prefix="/audit", tags=["监控审计"])
app.include_router(admin_router, prefix="/admin", tags=["平台管理"])
app.include_router(plugin_router, prefix="/plugins", tags=["插件"])


@app.get("/health", tags=["系统"])
async def health_check():
    return {"status": "ok", "version": "0.1.0"}
