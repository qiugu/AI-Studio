from collections.abc import AsyncIterable, Iterable
from typing import Any

from sse_starlette.event import JSONServerSentEvent
from sse_starlette.sse import EventSourceResponse

SSE_PING_INTERVAL_SECONDS = 15
SSE_SEND_TIMEOUT_SECONDS = 30


def json_sse_event(event: str, data: Any) -> JSONServerSentEvent:
    """Create a UTF-8 JSON SSE event while preserving non-ASCII text."""
    return JSONServerSentEvent(event=event, data=data)


def create_sse_response(
    content: AsyncIterable[Any] | Iterable[Any],
) -> EventSourceResponse:
    """Create an SSE response with shared production transport settings."""
    return EventSourceResponse(
        content,
        ping=SSE_PING_INTERVAL_SECONDS,
        send_timeout=SSE_SEND_TIMEOUT_SECONDS,
    )
