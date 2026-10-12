import logging
import time
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.database import sessionLocal
from app.models.audit_log import AuditLog

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


def _parse_resource(path: str) -> tuple[str, str | None]:
    """从路径解析资源类型与资源 ID。如 /api/ai-models/123 -> ('ai-models', '123')。"""
    normalized = path.removeprefix("/api").strip("/")
    parts = [p for p in normalized.split("/") if p]
    resource = parts[0] if parts else ""
    resource_id = parts[1] if len(parts) > 1 else None
    return resource, resource_id


class AuditMiddleware(BaseHTTPMiddleware):
    """
    审计日志中间件：自动记录写操作（POST/PUT/PATCH/DELETE）到 audit_logs 表。
    tenant_id / user_id 由 TenantMiddleware / get_current_user 注入 request.state。
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

        # 仅在已解析出租户时记录（写操作均需认证，tenant_id 必然存在）
        tenant_id = getattr(request.state, "tenant_id", None)
        if tenant_id is None:
            return response

        try:
            user_id = getattr(request.state, "user_id", None)
            resource, resource_id = _parse_resource(path)
            ip_address = request.client.host if request.client else None

            log = AuditLog(
                tenant_id=tenant_id,
                user_id=user_id,
                action=request.method,
                resource=resource,
                resource_id=resource_id,
                method=request.method,
                path=path,
                status_code=response.status_code,
                ip_address=ip_address,
                duration_ms=duration_ms,
            )
            db = sessionLocal()
            try:
                db.add(log)
                db.commit()
            finally:
                db.close()
        except Exception as e:
            logger.warning("AuditMiddleware write error: %s", e)

        return response
