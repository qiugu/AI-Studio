from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from pwdlib import PasswordHash

from app.core.config import config

pwd_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return pwd_hash.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_hash.verify(plain_password, hashed_password)


def create_access_token(user_id: int, tenant_id: int) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=config.jwt_access_token_expire_minutes)
    to_encode: dict[str, Any] = {
        "sub": str(user_id),
        "tid": tenant_id,
        "exp": expire,
        "type": "access",
    }
    return jwt.encode(
        to_encode,
        config.jwt_secret_key.get_secret_value(),
        algorithm=config.jwt_algorithm,
    )


def create_refresh_token(user_id: int) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=config.jwt_refresh_token_expire_days)
    to_encode: dict[str, Any] = {
        "sub": str(user_id),
        "exp": expire,
        "type": "refresh",
    }
    return jwt.encode(
        to_encode,
        config.jwt_secret_key.get_secret_value(),
        algorithm=config.jwt_algorithm,
    )


def decode_token(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(
            token,
            config.jwt_secret_key.get_secret_value(),
            algorithms=[config.jwt_algorithm],
        )
        return payload
    except jwt.InvalidTokenError:
        raise ValueError("Invalid token")


def generate_api_key() -> str:
    import secrets
    return f"ask-{secrets.token_urlsafe(32)}"
