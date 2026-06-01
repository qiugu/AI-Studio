import logging
import time
from typing import Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

# 每个 IP 每分钟最大请求数（默认限流）
_DEFAULT_LIMIT = 200
_WINDOW_SECONDS = 60

# 登录/注册接口单独限流（更严格）
_AUTH_LIMIT = 20
_AUTH_PATHS = {"/auth/login", "/auth/register"}


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    基于 Redis 的滑动窗口限流中间件。
    Redis 不可用时降级为放行（fail open）。
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        from app.core.redis import get_redis
        redis = await get_redis()
        if redis is None:
            # Redis 不可用，跳过限流
            return await call_next(request)

        # 获取客户端 IP
        client_ip = self._get_client_ip(request)
        path = request.url.path.removeprefix("/api")

        # 确定限流参数
        limit = _AUTH_LIMIT if any(path.startswith(p) for p in _AUTH_PATHS) else _DEFAULT_LIMIT
        window = _WINDOW_SECONDS

        key = f"rate_limit:{client_ip}:{path}"
        now = time.time()
        window_start = now - window

        try:
            pipe = redis.pipeline()
            # 移除窗口外的请求记录
            await pipe.zremrangebyscore(key, 0, window_start)
            # 记录本次请求
            await pipe.zadd(key, {str(now): now})
            # 统计窗口内请求数
            await pipe.zcard(key)
            # 设置 key 过期时间
            await pipe.expire(key, window * 2)
            results = await pipe.execute()

            count = results[2]
            if count > limit:
                logger.warning("Rate limit exceeded: ip=%s path=%s count=%d", client_ip, path, count)
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
        except Exception as e:
            logger.warning("RateLimitMiddleware error: %s", e)

        return await call_next(request)

    @staticmethod
    def _get_client_ip(request: Request) -> str:
        # 优先从代理头获取真实 IP
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip
        if request.client:
            return request.client.host
        return "unknown"
