import asyncio
import logging
from typing import Optional

from redis.asyncio import Redis
from redis.asyncio.retry import Retry
from redis.backoff import ExponentialBackoff
from redis.exceptions import ConnectionError, TimeoutError

from app.core.config import config

logger = logging.getLogger(__name__)

redis_client: Optional[Redis] = None


async def init_redis() -> None:
    global redis_client

    try:
        redis_client = Redis(
            host=config.redis_host,
            port=config.redis_port,
            db=config.redis_db,
            password=config.redis_password.get_secret_value() if config.redis_password.get_secret_value() else None,
            decode_responses=True,
            max_connections=50,
            retry_on_error=[ConnectionError, TimeoutError],
            retry=Retry(ExponentialBackoff(cap=10, base=1), retries=3),
            socket_connect_timeout=5,
            socket_timeout=10,
            health_check_interval=30,
        )

        await redis_client.ping()
        logger.info("Redis connected successfully")
    except Exception as e:
        logger.warning("Redis connection failed, running without cache: %s", e)
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
    try:
        await redis_client.ping()
        return redis_client
    except Exception:
        logger.exception("Redis ping failed")
        return None
