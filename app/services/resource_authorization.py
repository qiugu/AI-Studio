"""Resource-level authorization layered on top of tenant RBAC."""
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.authorization import (
    AuthorizationDecision,
    AuthorizationService,
    remember_authorization_decision,
)
from app.core.membership import effective_role_ids
from app.core.exceptions import ForbiddenException, NotFoundException, ValidationException
from app.core.permissions import get_permission_definition, get_permission_definitions
from app.models.resource_grant import ResourceGrant
from app.models.role import Role
from app.models.tenant import Tenant
from app.models.user import User
from app.models.user_role import user_role
from app.services.authorization_audit import AuthorizationAuditService


class ResourceAuthorizationService:
    """Evaluate tenant RBAC, resource ownership, publication, and grants."""

    def __init__(self, db: Session):
        self.db = db
        self.authorization = AuthorizationService(db)

    def check(
        self,
        actor: User,
        tenant_id: str,
        resource: str,
        action: str,
        resource_obj: Any,
    ) -> AuthorizationDecision:
        base = self.authorization.check_permission(
            actor,
            tenant_id,
            resource,
            action,
            resource_obj=resource_obj,
        )
        if not base.allowed:
            return base

        if getattr(resource_obj, "deleted_at", None) is not None:
            return self._deny(base, "resource_deleted")

        target_id = str(getattr(resource_obj, "id", ""))
        if getattr(resource_obj, "status", None) == "published":
            return base

        if str(getattr(resource_obj, "created_by", "")) == str(actor.id):
            return self._allow(base, "resource_owner_granted")

        if action in {"update", "delete", "publish", "tools_manage"}:
            return self._allow(base, "resource_management_granted")

        if self._has_active_grant(actor, tenant_id, resource, target_id, action):
            return self._allow(base, "resource_grant_granted")

        return self._deny(base, "resource_unpublished")

    def require(
        self,
        actor: User,
        tenant_id: str,
        resource: str,
        action: str,
        resource_obj: Any,
    ) -> AuthorizationDecision:
        decision = self.check(actor, tenant_id, resource, action, resource_obj)
        if not decision.allowed:
            raise ForbiddenException(resource, action)
        return decision

    def allowed_actions(
        self,
        actor: User,
        tenant_id: str,
        resource: str,
        resource_obj: Any,
    ) -> list[str]:
        """Return effective actions for a resource instance.

        This is intentionally calculated by the same PDP used by mutation and
        execution endpoints, so list/detail responses cannot drift from the
        actual enforcement rules.
        """
        return [
            definition.action
            for definition in get_permission_definitions(resource)
            if self.check(
                actor,
                tenant_id,
                resource,
                definition.action,
                resource_obj,
            ).allowed
        ]

    def _has_active_grant(
        self,
        actor: User,
        tenant_id: str,
        resource: str,
        resource_id: str,
        action: str,
    ) -> bool:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        role_ids = (
            select(Role.id)
            .where(
                Role.id.in_(effective_role_ids(actor.id, tenant_id)),
                Role.tenant_id == tenant_id,
                Role.status.is_(True),
            )
        )
        grants = (
            self.db.query(ResourceGrant)
            .filter(
                ResourceGrant.tenant_id == tenant_id,
                ResourceGrant.resource_type == resource,
                ResourceGrant.resource_id == resource_id,
                ResourceGrant.subject_type == "role",
                ResourceGrant.subject_id.in_(role_ids),
                ResourceGrant.revoked_at.is_(None),
            )
            .all()
        )
        return any(
            action in (grant.actions or [])
            and (grant.expires_at is None or grant.expires_at > now)
            for grant in grants
        )

    @staticmethod
    def _allow(
        decision: AuthorizationDecision, reason: str
    ) -> AuthorizationDecision:
        return remember_authorization_decision(AuthorizationDecision(
            allowed=True,
            reason=reason,
            permission_key=decision.permission_key,
            tenant_id=decision.tenant_id,
            target_type=decision.target_type,
            target_id=decision.target_id,
        ))

    @staticmethod
    def _deny(
        decision: AuthorizationDecision, reason: str
    ) -> AuthorizationDecision:
        return remember_authorization_decision(AuthorizationDecision(
            allowed=False,
            reason=reason,
            permission_key=decision.permission_key,
            tenant_id=decision.tenant_id,
            target_type=decision.target_type,
            target_id=decision.target_id,
        ))


class ResourceGrantService:
    """Create and revoke role-based resource grants with tenant governance checks."""

    def __init__(self, db: Session):
        self.db = db
        self.authorization = AuthorizationService(db)

    def create_grant(
        self,
        actor: User,
        tenant_id: str,
        resource: str,
        resource_obj: Any,
        *,
        subject_role_id: str,
        actions: list[str],
        expires_at: datetime | None = None,
    ) -> ResourceGrant:
        self._require_manager(actor, tenant_id)
        if getattr(resource_obj, "tenant_id", None) != tenant_id:
            raise ForbiddenException(resource, "share")
        if getattr(resource_obj, "deleted_at", None) is not None:
            raise NotFoundException(resource, str(getattr(resource_obj, "id", "")))
        if not actions:
            raise ValidationException("至少需要授予一个资源动作")

        normalized_actions = list(dict.fromkeys(actions))
        for action in normalized_actions:
            definition = get_permission_definition(resource, action)
            if definition.scope != "tenant" or not definition.is_delegable:
                raise ValidationException(f"资源动作不可委派: {resource}.{action}")

        role = (
            self.db.query(Role)
            .filter(
                Role.id == subject_role_id,
                Role.tenant_id == tenant_id,
                Role.status.is_(True),
            )
            .first()
        )
        if role is None:
            raise NotFoundException("Role", subject_role_id)

        grant = ResourceGrant(
            tenant_id=tenant_id,
            resource_type=resource,
            resource_id=str(resource_obj.id),
            subject_type="role",
            subject_id=role.id,
            actions=normalized_actions,
            expires_at=self._naive_utc(expires_at),
            created_by=str(actor.id),
        )
        self.db.add(grant)
        self.db.flush()
        AuthorizationAuditService(self.db).record_change(
            actor=actor,
            tenant_id=tenant_id,
            action="RESOURCE_GRANT_CREATED",
            resource=resource,
            target_type="ResourceGrant",
            target_id=grant.id,
            permission_key="tenant.roles_manage",
            reason="resource_grant_created",
            metadata={
                "resource_id": str(resource_obj.id),
                "subject_role_id": subject_role_id,
                "actions": normalized_actions,
            },
        )
        return grant

    def revoke_grant(
        self,
        actor: User,
        tenant_id: str,
        grant_id: str,
        *,
        resource: str | None = None,
        resource_id: str | None = None,
    ) -> ResourceGrant:
        self._require_manager(actor, tenant_id)
        query = self.db.query(ResourceGrant).filter(
            ResourceGrant.id == grant_id,
            ResourceGrant.tenant_id == tenant_id,
        )
        if resource is not None:
            query = query.filter(ResourceGrant.resource_type == resource)
        if resource_id is not None:
            query = query.filter(ResourceGrant.resource_id == resource_id)
        grant = query.first()
        if grant is None:
            raise NotFoundException("ResourceGrant", grant_id)
        if grant.revoked_at is None:
            grant.revoked_at = datetime.now(timezone.utc).replace(tzinfo=None)
            self.db.flush()
            AuthorizationAuditService(self.db).record_change(
                actor=actor,
                tenant_id=tenant_id,
                action="RESOURCE_GRANT_REVOKED",
                resource=grant.resource_type,
                target_type="ResourceGrant",
                target_id=grant.id,
                permission_key="tenant.roles_manage",
                reason="resource_grant_revoked",
                metadata={"resource_id": grant.resource_id},
            )
        return grant

    def _require_manager(self, actor: User, tenant_id: str) -> None:
        tenant = self.db.query(Tenant).filter(Tenant.id == tenant_id).first()
        if tenant is not None and tenant.owner_id == actor.id:
            return
        self.authorization.require_permission(
            actor,
            tenant_id,
            "tenant",
            "roles_manage",
        )

    @staticmethod
    def _naive_utc(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is not None:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value
