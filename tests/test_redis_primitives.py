from hashlib import sha256
import inspect


def test_token_blacklist_key_hashes_the_token():
    from app.core.redis import token_blacklist_key

    token = "header.payload.signature"
    key = token_blacklist_key(token)

    assert key.startswith("ai-studio:prod:auth:token-blacklist:")
    assert token not in key
    assert sha256(token.encode()).hexdigest() in key


def test_cache_ttl_is_positive_and_has_jitter(monkeypatch):
    from app.core.redis import ttl_with_jitter

    monkeypatch.setattr("app.core.redis.random.randint", lambda _a, _b: 7)
    assert ttl_with_jitter(60, 10) == 67


def test_key_parts_are_escaped():
    from app.core.redis import build_redis_key

    assert build_redis_key("rate-limit", "ip", "2001:db8::1") == (
        "ai-studio:prod:rate-limit:ip:2001%3Adb8%3A%3A1"
    )


def test_domain_key_builders_use_the_same_namespace():
    from app.core.redis import (
        authorization_cache_key,
        rate_limit_key,
        vector_layout_cache_key,
    )

    assert rate_limit_key("127.0.0.1", "/auth/login").startswith(
        "ai-studio:prod:rate-limit:ip:"
    )
    assert authorization_cache_key(
        "user-1", "tenant-1", 3, "agent", "chat", "legacy", 0
    ).startswith("ai-studio:prod:cache:authorization:")
    assert vector_layout_cache_key("kb-1").startswith(
        "ai-studio:prod:cache:vector-layout:"
    )


def test_sync_and_async_clients_use_matching_retry_types():
    from redis.asyncio.retry import Retry as AsyncRetry

    from app.core.redis import _async_redis_options

    async_retry = _async_redis_options()["retry"]

    assert isinstance(async_retry, AsyncRetry)


def test_redis_boundary_is_async_only():
    import app.core.redis as redis_module

    assert not hasattr(redis_module, "sync_redis_client")
    assert not hasattr(redis_module, "get_sync_redis")
    assert inspect.iscoroutinefunction(redis_module.cache_get_json)
    assert inspect.iscoroutinefunction(redis_module.cache_set_json)
    assert inspect.iscoroutinefunction(redis_module.acquire_lock)
    assert inspect.iscoroutinefunction(redis_module.release_lock)
