import asyncio
from unittest.mock import AsyncMock

import pytest


def test_tokens_have_unique_jti_claims():
    from app.core.security import (
        create_access_token,
        create_refresh_token,
        decode_token,
    )

    access = decode_token(create_access_token("u1", "t1"))
    refresh = decode_token(create_refresh_token("u1"))

    assert access["jti"]
    assert refresh["jti"]
    assert access["jti"] != refresh["jti"]


def test_blacklist_writes_the_shared_hashed_key(monkeypatch):
    from app.api import auth as auth_api
    from app.core.redis import token_blacklist_key
    from app.core.security import create_access_token

    redis = AsyncMock()
    monkeypatch.setattr(auth_api, "get_redis", AsyncMock(return_value=redis))
    token = create_access_token("u1", "t1")

    assert asyncio.run(auth_api._blacklist_token(token)) is True

    written_key = redis.setex.await_args.args[0]
    assert written_key == token_blacklist_key(token)
    assert token not in written_key


def test_blacklist_read_uses_the_same_key(monkeypatch):
    from app.api import auth as auth_api
    from app.core.redis import token_blacklist_key
    from app.core.security import create_access_token

    redis = AsyncMock()
    redis.get.return_value = "1"
    monkeypatch.setattr(auth_api, "get_redis", AsyncMock(return_value=redis))
    token = create_access_token("u1", "t1")

    assert asyncio.run(auth_api._is_token_blacklisted(token)) is True
    redis.get.assert_awaited_once_with(token_blacklist_key(token))


def test_request_authentication_fails_closed_when_redis_is_unavailable(monkeypatch):
    from app.core.dependencies import get_current_user
    from app.core.exceptions import ServiceUnavailableException

    monkeypatch.setattr("app.core.dependencies.get_redis", AsyncMock(return_value=None))

    with pytest.raises(ServiceUnavailableException):
        asyncio.run(get_current_user(object(), token="not-used", db=object()))
