import json
import logging
import time
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

# 需要记录审计日志的写操作方法
_AUDIT_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# 不记录审计日志的路径前缀
_SKIP_PATHS = {
    "/auth/login",
    "/auth/logout",
    "/auth/refresh",
    "/auth/register",
    "/docs",
    "/openapi.json",
    "/redoc",
}


class AuditMiddleware(BaseHTTPMiddleware):
    """
    审计日志中间件：自动记录写操作（POST/PUT/PATCH/DELETE）到日志。
    阶段一仅写入应用日志；阶段八引入 audit_logs 表后替换为 DB 写入。
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.method not in _AUDIT_METHODS:
            return await call_next(request)

        path = request.url.path
        normalized = path.removeprefix("/api")
        if any(normalized.startswith(p) for p in _SKIP_PATHS):
            return await call_next(request)

        start_time = time.monotonic()
        response = await call_next(request)
        duration_ms = int((time.monotonic() - start_time) * 1000)

        try:
            user_id: int | None = None
            tenant_id: int | None = None
            if hasattr(request.state, "user"):
                user_id = getattr(request.state.user, "id", None)
                tenant_id = getattr(request.state.user, "tenant_id", None)
            elif hasattr(request.state, "tenant_id"):
                tenant_id = request.state.tenant_id

            logger.info(
                "AUDIT | method=%s path=%s status=%d user_id=%s tenant_id=%s duration_ms=%d",
                request.method,
                path,
                response.status_code,
                user_id,
                tenant_id,
                duration_ms,
            )
        except Exception as e:
            logger.warning("AuditMiddleware logging error: %s", e)

        return response
