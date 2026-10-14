from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.authorization import AuthorizationDecision
from app.core.database import Base
from app.models.audit_log import AuditLog
from app.models.authorization_outbox import AuthorizationOutbox
from app.services.authorization_audit import AuthorizationAuditService
from app.services.authorization_outbox import AuthorizationOutboxService


def test_authorization_decision_is_recorded_with_structured_context():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    actor = SimpleNamespace(id="user-1")
    decision = AuthorizationDecision(
        allowed=False,
        reason="resource_unpublished",
        permission_key="agent.read",
        tenant_id="tenant-1",
        target_type="Agent",
        target_id="agent-1",
    )

    with Session(engine) as db:
        log = AuthorizationAuditService(db).record_decision(
            actor=actor,
            decision=decision,
            request_id="request-1",
            method="GET",
            path="/api/agents/agent-1",
            status_code=403,
            ip_address="127.0.0.1",
            user_agent="pytest",
            metadata={"source": "resource_policy"},
        )
        db.commit()

        saved = db.query(AuditLog).one()

    assert log is saved
    assert saved.decision == "deny"
    assert saved.permission_key == "agent.read"
    assert saved.target_type == "Agent"
    assert saved.target_id == "agent-1"
    assert saved.reason == "resource_unpublished"
    assert saved.request_id == "request-1"
    assert saved.user_agent == "pytest"
    assert saved.metadata_json == {"source": "resource_policy"}


def test_authorization_change_writes_redacted_audit_and_outbox_in_same_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    actor = SimpleNamespace(id="owner-1")

    with Session(engine) as db:
        log = AuthorizationAuditService(db).record_change(
            actor=actor,
            tenant_id="tenant-1",
            action="OWNER_TRANSFER",
            resource="tenant",
            target_type="TenantOwner",
            target_id="user-2",
            permission_key="tenant.settings",
            reason="owner_transfer_completed",
            metadata={"current_password": "do-not-store", "new_owner_id": "user-2"},
        )
        db.commit()

        outbox = db.query(AuthorizationOutbox).one()
        audit_metadata = db.query(AuditLog).one().metadata_json

    assert audit_metadata["current_password"] == "[REDACTED]"
    assert outbox.status == "pending"
    assert outbox.payload["metadata"]["current_password"] == "[REDACTED]"


def test_authorization_outbox_supports_claim_success_and_retry():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    actor = SimpleNamespace(id="owner-1")

    with Session(engine) as db:
        AuthorizationAuditService(db).record_change(
            actor=actor,
            tenant_id="tenant-1",
            action="ROLE_UPDATED",
            resource="role",
            target_type="Role",
            target_id="role-1",
            permission_key="role.update",
            reason="role_updated",
        )
        db.commit()
        service = AuthorizationOutboxService(db)
        event = service.list_pending(tenant_id="tenant-1")[0]
        claimed = service.claim(event.id)
        assert claimed.status == "processing"
        assert claimed.attempts == 1
        service.mark_failed(event.id, "temporary delivery error", retry_at=None)
        assert db.get(AuthorizationOutbox, event.id).status == "failed"
