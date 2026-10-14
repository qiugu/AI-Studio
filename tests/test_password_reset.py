from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.core.exceptions import ValidationException
from app.core.security import verify_password
from app.models import AuditLog, PasswordResetToken, User
from app.services.admin import create_tenant
from app.services.user import change_my_password, complete_password_reset, create_user, request_password_reset
from app.main import app


def test_password_reset_workflow_exposes_separate_admin_and_completion_routes():
    paths = {(route.path, tuple(sorted(getattr(route, "methods", set())))) for route in app.routes}

    assert ("/users/{user_id}/password-reset", ("POST",)) in paths
    assert ("/auth/password-reset", ("POST",)) in paths
    assert ("/auth/change-password", ("POST",)) in paths


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_password_reset_token_is_hashed_single_use_and_revokes_credentials(db):
    tenant = create_tenant(
        {
            "name": "Password Reset Tenant",
            "admin_email": "reset-owner@example.com",
            "admin_password": "password123",
        },
        db,
    )
    owner = db.query(User).filter(User.id == tenant.owner_id).one()
    target = create_user(
        email="reset-target@example.com",
        password="old-password",
        tenant_id=tenant.id,
        db=db,
        check_quota=False,
    )
    old_authz_version = target.authz_version
    old_credentials_version = target.credentials_version

    target, raw_token = request_password_reset(
        target.id,
        tenant.id,
        db,
        actor=owner,
        current_password="password123",
    )
    record = db.query(PasswordResetToken).one()
    assert record.token_hash != raw_token
    assert len(record.token_hash) == 64

    complete_password_reset(raw_token, "new-password-123", db)
    db.refresh(target)
    assert verify_password("new-password-123", target.password_hash)
    assert target.authz_version == old_authz_version + 1
    assert target.credentials_version == old_credentials_version + 1
    assert record.used_at is not None

    with pytest.raises(ValidationException, match="无效或已过期"):
        complete_password_reset(raw_token, "another-password-123", db)

    completion = (
        db.query(AuditLog)
        .filter(
            AuditLog.action == "USER_PASSWORD_RESET_COMPLETED",
            AuditLog.target_id == target.id,
        )
        .one()
    )
    assert "password" not in str(completion.metadata_json).lower()
    assert raw_token not in str(completion.metadata_json)


def test_expired_password_reset_token_is_rejected(db):
    tenant = create_tenant(
        {
            "name": "Expired Reset Tenant",
            "admin_email": "expired-reset-owner@example.com",
            "admin_password": "password123",
        },
        db,
    )
    target = create_user(
        email="expired-reset-target@example.com",
        password="old-password",
        tenant_id=tenant.id,
        db=db,
        check_quota=False,
    )
    target, raw_token = request_password_reset(
        target.id,
        tenant.id,
        db,
        actor=db.query(User).filter(User.id == tenant.owner_id).one(),
        current_password="password123",
    )
    record = db.query(PasswordResetToken).one()
    record.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=1)
    db.flush()

    with pytest.raises(ValidationException, match="无效或已过期"):
        complete_password_reset(raw_token, "new-password-123", db)


def test_user_can_change_own_password_and_revoke_existing_credentials(db):
    tenant = create_tenant(
        {
            "name": "Self Password Tenant",
            "admin_email": "self-password-owner@example.com",
            "admin_password": "password123",
        },
        db,
    )
    owner = db.query(User).filter(User.id == tenant.owner_id).one()
    old_authz_version = owner.authz_version
    old_credentials_version = owner.credentials_version

    change_my_password(owner, "password123", "new-owner-password-123", db)
    db.refresh(owner)

    assert verify_password("new-owner-password-123", owner.password_hash)
    assert owner.authz_version == old_authz_version + 1
    assert owner.credentials_version == old_credentials_version + 1
    audit = (
        db.query(AuditLog)
        .filter(
            AuditLog.action == "USER_PASSWORD_CHANGED",
            AuditLog.target_id == owner.id,
        )
        .one()
    )
    assert "new-owner-password-123" not in str(audit.metadata_json)
