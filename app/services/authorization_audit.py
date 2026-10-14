"""Structured audit writes for authorization decisions and changes."""
from typing import Any, Mapping

from sqlalchemy.orm import Session

from app.core.authorization import AuthorizationDecision
from app.models.audit_log import AuditLog
from app.models.authorization_outbox import AuthorizationOutbox


_SENSITIVE_METADATA_KEYS = {"password", "current_password", "api_key", "secret", "token"}


def _safe_metadata(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): "[REDACTED]" if str(key).lower() in _SENSITIVE_METADATA_KEYS else _safe_metadata(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_safe_metadata(item) for item in value]
    return value


class AuthorizationAuditService:
    def __init__(self, db: Session):
        self.db = db

    def record_decision(
        self,
        *,
        actor: Any,
        decision: AuthorizationDecision,
        request_id: str | None = None,
        method: str = "AUTHZ",
        path: str = "",
        status_code: int = 200,
        ip_address: str | None = None,
        user_agent: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> AuditLog:
        resource = decision.permission_key.split(".", 1)[0]
        log = AuditLog(
            tenant_id=decision.tenant_id or "",
            user_id=str(getattr(actor, "id", "")) or None,
            action="AUTHZ",
            resource=resource,
            resource_id=decision.target_id,
            method=method,
            path=path,
            status_code=status_code,
            ip_address=ip_address,
            user_agent=user_agent,
            request_id=request_id,
            decision="allow" if decision.allowed else "deny",
            permission_key=decision.permission_key,
            target_type=decision.target_type,
            target_id=decision.target_id,
            reason=decision.reason,
            metadata_json=dict(metadata) if metadata is not None else None,
        )
        self.db.add(log)
        self.db.flush()
        return log

    def record_change(
        self,
        *,
        actor: Any,
        tenant_id: str,
        action: str,
        resource: str,
        target_type: str,
        target_id: str,
        permission_key: str,
        reason: str,
        request_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> AuditLog:
        """Record a successful authorization-sensitive state change."""
        safe_metadata = _safe_metadata(dict(metadata)) if metadata is not None else {}
        log = AuditLog(
            tenant_id=tenant_id,
            user_id=str(getattr(actor, "id", "")) or None,
            action=action,
            resource=resource,
            resource_id=target_id,
            method="AUTHZ",
            path="",
            status_code=200,
            request_id=request_id,
            decision="allow",
            permission_key=permission_key,
            target_type=target_type,
            target_id=target_id,
            reason=reason,
            metadata_json=safe_metadata,
        )
        self.db.add(log)
        self.db.add(
            AuthorizationOutbox(
                tenant_id=tenant_id,
                actor_id=str(getattr(actor, "id", "")) or None,
                event_type=action,
                target_type=target_type,
                target_id=target_id,
                payload={
                    "action": action,
                    "resource": resource,
                    "permission_key": permission_key,
                    "reason": reason,
                    "metadata": safe_metadata,
                },
                status="pending",
            )
        )
        self.db.flush()
        return log
