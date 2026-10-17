import logging
import time
import uuid
from dataclasses import dataclass
from typing import Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.redis import get_redis, rate_limit_key, ttl_with_jitter

logger = logging.getLogger(__name__)

# 每个 IP 每分钟最大请求数（默认限流）
_DEFAULT_LIMIT = 200
_WINDOW_SECONDS = 60

# 登录/注册接口单独限流（更严格）
_AUTH_LIMIT = 20
_SECURITY_SENSITIVE_PATHS = {
    "/auth/login",
    "/auth/register",
    "/auth/refresh",
    "/auth/password-reset",
    "/auth/resend-verification",
    "/auth/change-password",
    "/auth/verify-email",
}
_AUTH_PATHS = _SECURITY_SENSITIVE_PATHS

_ATOMIC_SLIDING_WINDOW_SCRIPT = """
local key = KEYS[1]
local window_start = tonumber(ARGV[1])
local now = tonumber(ARGV[2])
local member = ARGV[3]
local ttl = tonumber(ARGV[4])
redis.call('ZREMRANGEBYSCORE', key, 0, window_start)
redis.call('ZADD', key, now, member)
local count = redis.call('ZCARD', key)
redis.call('EXPIRE', key, ttl)
return count
"""


def _build_key(client_ip: str, path: str) -> str:
    return rate_limit_key(client_ip, path)


@dataclass(frozen=True)
class RateLimitResult:
    count: int
    limit: int
    decision: str = "allow"

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.count)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    基于 Redis 的滑动窗口限流中间件。
    普通接口在 Redis 不可用时放行；认证、密码和刷新接口 fail closed。
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        redis = await get_redis()
        path = request.url.path.removeprefix("/api")
        strict = path in _SECURITY_SENSITIVE_PATHS
        if redis is None:
            if strict:
                return self._redis_unavailable_response()
            return await call_next(request)

        # 获取客户端 IP
        client_ip = self._get_client_ip(request)

        # 确定限流参数
        limit = _AUTH_LIMIT if any(path.startswith(p) for p in _AUTH_PATHS) else _DEFAULT_LIMIT
        window = _WINDOW_SECONDS
        result = await self._consume(
            redis,
            _build_key(client_ip, path),
            limit=limit,
            window=window,
            now=time.time(),
            ttl=ttl_with_jitter(window * 2, window),
        )

        if result.decision == "error":
            if strict:
                return self._redis_unavailable_response()
            return await call_next(request)

        if result.count > limit:
            logger.warning(
                "Rate limit exceeded: ip=%s path=%s count=%d",
                client_ip,
                path,
                result.count,
            )
            return JSONResponse(
                status_code=429,
                content={
                    "code": 429,
                    "message": "Too many requests, please try again later",
                    "data": None,
                },
                headers={
                    "Retry-After": str(window),
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(result.remaining)
        return response

    async def _consume(
        self,
        redis,
        key: str,
        *,
        limit: int,
        window: int,
        now: float,
        ttl: int | None = None,
    ) -> RateLimitResult:
        try:
            count = int(
                await redis.eval(
                    _ATOMIC_SLIDING_WINDOW_SCRIPT,
                    1,
                    key,
                    now - window,
                    now,
                    uuid.uuid4().hex,
                    ttl if ttl is not None else window * 2,
                )
            )
            return RateLimitResult(count=count, limit=limit)
        except Exception as exc:  # noqa: BLE001 - limiter must not crash requests
            logger.warning("RateLimitMiddleware error: %s", exc)
            return RateLimitResult(count=0, limit=limit, decision="error")

    @staticmethod
    def _redis_unavailable_response() -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={
                "code": 503,
                "message": "Security rate limiting is temporarily unavailable",
                "data": None,
            },
            headers={"Retry-After": "1"},
        )

    @staticmethod
    def _get_client_ip(request: Request) -> str:
        # 仅信任由受信反向代理（nginx）基于 TCP 对端地址写入的 X-Real-IP。
        # nginx 以 ``proxy_set_header X-Real-IP $remote_addr`` 覆盖该头，客户端无法伪造（S7）。
        # 直连 / 开发环境无该头时，回退到 TCP 对端地址。
        # 不再读取客户端可控的 X-Forwarded-For 首段，防止攻击者用不同 XFF 绕过限流。
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip.strip()
        if request.client:
            return request.client.host
        return "unknown"
