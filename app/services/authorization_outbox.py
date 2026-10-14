"""Claim/retry primitives for authorization change events."""
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundException
from app.models.authorization_outbox import AuthorizationOutbox


class AuthorizationOutboxService:
    def __init__(self, db: Session):
        self.db = db

    def list_pending(self, *, tenant_id: str | None = None, limit: int = 100):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        query = self.db.query(AuthorizationOutbox).filter(
            AuthorizationOutbox.status == "pending",
            (
                AuthorizationOutbox.available_at.is_(None)
                | (AuthorizationOutbox.available_at <= now)
            ),
        )
        if tenant_id is not None:
            query = query.filter(AuthorizationOutbox.tenant_id == tenant_id)
        return query.order_by(AuthorizationOutbox.created_at).limit(limit).all()

    def claim(self, event_id: str) -> AuthorizationOutbox:
        event = (
            self.db.query(AuthorizationOutbox)
            .filter(
                AuthorizationOutbox.id == event_id,
                AuthorizationOutbox.status == "pending",
            )
            .with_for_update()
            .first()
        )
        if event is None:
            raise NotFoundException("AuthorizationOutbox", event_id)
        event.status = "processing"
        event.attempts = int(event.attempts or 0) + 1
        self.db.flush()
        return event

    def mark_processed(self, event_id: str) -> AuthorizationOutbox:
        event = self.db.get(AuthorizationOutbox, event_id)
        if event is None:
            raise NotFoundException("AuthorizationOutbox", event_id)
        event.status = "processed"
        event.processed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        self.db.flush()
        return event

    def mark_failed(
        self,
        event_id: str,
        error: str,
        *,
        retry_at: datetime | None = None,
    ) -> AuthorizationOutbox:
        event = self.db.get(AuthorizationOutbox, event_id)
        if event is None:
            raise NotFoundException("AuthorizationOutbox", event_id)
        event.status = "pending" if retry_at is not None else "failed"
        event.available_at = retry_at
        event.last_error = error[:2000]
        self.db.flush()
        return event
