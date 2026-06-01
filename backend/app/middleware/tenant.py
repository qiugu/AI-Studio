import logging
from typing import Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.database import sessionLocal
from app.models.tenant import Tenant

logger = logging.getLogger(__name__)

# 无需租户检查的路径白名单
_WHITELIST_PATHS = {
    "/auth/login",
    "/auth/register",
    "/auth/refresh",
    "/docs",
    "/openapi.json",
    "/redoc",
}


class TenantMiddleware(BaseHTTPMiddleware):
    """
    租户隔离中间件：
    - 白名单路径跳过检查
    - 从 JWT token 解析 tenant_id 并注入 request.state
    - 校验租户状态（禁用 → 403 TENANT_DISABLED）
    - 校验软删除（deleted_at 非空 → 403 TENANT_NOT_FOUND）
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path

        # 去除 /api 前缀后匹配白名单
        normalized = path.removeprefix("/api")
        if any(normalized.startswith(p) for p in _WHITELIST_PATHS):
            return await call_next(request)

        # 尝试从 Authorization header 解析 tenant_id
        tenant_id: int | None = None
        authorization = request.headers.get("Authorization", "")
        if authorization.startswith("Bearer "):
            token = authorization.removeprefix("Bearer ").strip()
            try:
                from app.core.security import decode_token
                payload = decode_token(token)
                tenant_id = payload.get("tid")
            except Exception:
                pass  # token 解析失败，留给 dependencies 的 get_current_user 处理

        # 如果有 tenant_id，则校验租户状态
        if tenant_id is not None:
            try:
                db = sessionLocal()
                try:
                    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
                    if tenant is None or tenant.deleted_at is not None:
                        return JSONResponse(
                            status_code=403,
                            content={
                                "code": 403,
                                "message": "Tenant not found or has been deleted",
                                "data": None,
                            },
                        )
                    if not tenant.status:
                        return JSONResponse(
                            status_code=403,
                            content={
                                "code": 403,
                                "message": "Tenant is disabled",
                                "data": None,
                            },
                        )
                    # 注入 tenant_id 到 request.state
                    request.state.tenant_id = tenant_id
                    request.state.tenant = tenant
                finally:
                    db.close()
            except Exception as e:
                logger.exception("TenantMiddleware error: %s", e)

        return await call_next(request)
