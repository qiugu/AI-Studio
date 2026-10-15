"""Shared detection for configuration values that contain credentials."""

from typing import Any


SECRET_NAME_HINTS = (
    "key",
    "secret",
    "token",
    "password",
    "pwd",
    "credential",
    "authorization",
    "auth",
)


def is_sensitive_name(name: str) -> bool:
    """Return whether a configuration name conventionally represents a secret."""
    lowered = str(name).lower()
    return any(hint in lowered for hint in SECRET_NAME_HINTS)


def contains_sensitive_field(value: Any, name_hint: str = "") -> bool:
    """Detect credentials nested inside JSON-like configuration values."""
    if name_hint and is_sensitive_name(name_hint):
        return value is not None
    if isinstance(value, dict):
        return any(
            is_sensitive_name(str(key)) or contains_sensitive_field(item, str(key))
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(contains_sensitive_field(item) for item in value)
    return False
