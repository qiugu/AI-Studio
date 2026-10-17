import asyncio
from unittest.mock import AsyncMock

from redis.exceptions import TimeoutError


def test_rate_limit_uses_atomic_script_and_unique_member(monkeypatch):
    from app.middleware.rate_limit import RateLimitMiddleware

    redis = AsyncMock()
    redis.eval.return_value = 2
    middleware = object.__new__(RateLimitMiddleware)

    result = asyncio.run(
        middleware._consume(redis, "key", limit=20, window=60, now=100.0)
    )

    assert result.count == 2
    assert result.remaining == 18
    redis.eval.assert_awaited_once()
    script = redis.eval.await_args.args[0]
    assert "ZREMRANGEBYSCORE" in script
    assert "ZADD" in script
    assert "EXPIRE" in script
    assert redis.eval.await_args.args[1] == 1
    assert redis.eval.await_args.args[2] == "key"
    assert redis.eval.await_args.args[6] == 120


def test_rate_limit_failure_is_reported_as_error():
    from app.middleware.rate_limit import RateLimitMiddleware

    redis = AsyncMock()
    redis.eval.side_effect = TimeoutError()
    middleware = object.__new__(RateLimitMiddleware)

    result = asyncio.run(
        middleware._consume(redis, "key", limit=20, window=60, now=100.0)
    )

    assert result.decision == "error"


def test_rate_limit_key_uses_the_standard_builder(monkeypatch):
    from app.middleware import rate_limit

    monkeypatch.setattr(rate_limit, "rate_limit_key", lambda ip, path: f"standard:{ip}:{path}")
    assert rate_limit._build_key("127.0.0.1", "/auth/login") == (
        "standard:127.0.0.1:/auth/login"
    )
