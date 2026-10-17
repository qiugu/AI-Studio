import asyncio
import json
import logging
import random
from hashlib import sha256
from typing import Optional
from urllib.parse import quote
from uuid import uuid4

from redis.asyncio import Redis
from redis.asyncio.retry import Retry as AsyncRetry
from redis.backoff import ExponentialBackoff
from redis.exceptions import ConnectionError, TimeoutError

from app.core.config import config

logger = logging.getLogger(__name__)

redis_client: Optional[Redis] = None


def _common_redis_options() -> dict:
    password = config.redis_password.get_secret_value()
    return {
        "host": config.redis_host,
        "port": config.redis_port,
        "db": config.redis_db,
        "password": password or None,
        "decode_responses": True,
        "max_connections": 50,
        "retry_on_error": [ConnectionError, TimeoutError],
        "socket_connect_timeout": 5,
        "socket_timeout": 10,
        "health_check_interval": 30,
    }


def _async_redis_options() -> dict:
    options = _common_redis_options()
    options["retry"] = AsyncRetry(ExponentialBackoff(cap=10, base=1), retries=3)
    return options


def build_redis_key(*parts: object) -> str:
    """Build a namespaced key and escape each dynamic segment.

    Logical Redis databases are not security boundaries, so every key carries
    the application and environment namespace explicitly.
    """
    namespace = (config.app_name, config.env, *parts)
    return ":".join(quote(str(part), safe="-_.~") for part in namespace)


def token_blacklist_key(token: str) -> str:
    """Return a blacklist key without putting the raw token into Redis."""
    token_hash = sha256(token.encode("utf-8")).hexdigest()
    return build_redis_key("auth", "token-blacklist", token_hash)


def rate_limit_key(client_ip: str, path: str) -> str:
    return build_redis_key("rate-limit", "ip", client_ip, "route", path)


def authorization_cache_key(
    actor_id: str,
    tenant_id: str,
    authz_version: int,
    resource: str,
    action: str,
    membership_mode: str,
    membership_version: int,
) -> str:
    return build_redis_key(
        "cache",
        "authorization",
        actor_id,
        tenant_id,
        authz_version,
        membership_mode,
        membership_version,
        resource,
        action,
    )


def vector_layout_cache_key(collection_name: str) -> str:
    return build_redis_key("cache", "vector-layout", collection_name)


def vector_layout_lock_key(collection_name: str) -> str:
    return build_redis_key("lock", "vector-layout", collection_name)


def ttl_with_jitter(base_seconds: float, jitter_seconds: int = 30) -> int:
    base = max(1, int(base_seconds))
    jitter = max(0, int(jitter_seconds))
    return base + (random.randint(0, jitter) if jitter else 0)


def json_loads(value: object) -> object | None:
    if value is None:
        return None
    try:
        return json.loads(value if isinstance(value, str) else value.decode("utf-8"))
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError):
        return None


async def cache_get_json(client: Redis, key: str) -> object | None:
    return json_loads(await client.get(key))


async def cache_set_json(
    client: Redis,
    key: str,
    value: object,
    ttl_seconds: float,
    *,
    jitter_seconds: int = 30,
) -> bool:
    return bool(
        await client.setex(
            key,
            ttl_with_jitter(ttl_seconds, jitter_seconds),
            json.dumps(value, ensure_ascii=False, separators=(",", ":")),
        )
    )


async def acquire_lock(client: Redis, key: str, ttl_seconds: int = 5) -> str | None:
    token = uuid4().hex
    if await client.set(key, token, nx=True, ex=max(1, int(ttl_seconds))):
        return token
    return None


async def release_lock(client: Redis, key: str, token: str) -> None:
    script = (
        "if redis.call('get', KEYS[1]) == ARGV[1] then "
        "return redis.call('del', KEYS[1]) else return 0 end"
    )
    try:
        await client.eval(script, 1, key, token)
    except Exception:
        logger.debug("Unable to release Redis lock %s", key, exc_info=True)


async def init_redis() -> None:
    global redis_client

    try:
        redis_client = Redis(**_async_redis_options())
        await redis_client.ping()
        logger.info("Redis connected successfully")
    except Exception as e:
        logger.warning("Redis connection failed, running without cache: %s", e)
        if redis_client is not None:
            try:
                await redis_client.close()
            except Exception:
                logger.debug("Redis async client close failed", exc_info=True)
        redis_client = None


async def redis_close() -> None:
    global redis_client

    if redis_client is not None:
        try:
            await asyncio.wait_for(redis_client.close(), timeout=5)
        except Exception as e:
            logger.warning("Redis close error: %s", e)
        finally:
            redis_client = None

async def get_redis() -> Optional[Redis]:
    if redis_client is None:
        logger.warning("Redis client is not initialized")
        return None
    return redis_client
