"""Centralized tenant-aware authorization decisions."""
from dataclasses import dataclass
from contextvars import ContextVar
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.core.exceptions import ForbiddenException
from app.core.config import config
from app.core.permissions import get_permission_definition
from app.core.membership import effective_role_ids
from app.core.redis import (
    authorization_cache_key,
    cache_get_json,
    cache_set_json,
    get_redis,
)
from app.models.permission import Permission
from app.models.role import Role
from app.models.role_permission import role_permission
from app.models.membership_role import membership_role
from app.models.tenant import Tenant
from app.models.tenant_membership import TenantMembership
from app.models.user import User
from app.models.user_role import user_role


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AuthorizationDecision:
    allowed: bool
    reason: str
    permission_key: str
    tenant_id: str | None
    target_type: str | None = None
    target_id: str | None = None


_authorization_decision_ctx: ContextVar[AuthorizationDecision | None] = ContextVar(
    "authorization_decision_ctx", default=None
)

def clear_authorization_cache() -> None:
    """Compatibility hook retained for tests and lifecycle callers.

    Authorization decisions are now stored in Redis and are versioned by the
    user's authorization version.  There is no process-local cache to clear.
    """
    return None


def _authorization_cache_key(
    actor: User,
    tenant_id: str,
    resource: str,
    action: str,
    membership_version: int = 0,
) -> str:
    return authorization_cache_key(
        str(actor.id),
        str(tenant_id),
        int(actor.authz_version or 1),
        resource,
        action,
        str(getattr(config, "membership_read_mode", "legacy")),
        int(membership_version),
    )


def _cache_payload(decision: AuthorizationDecision) -> dict[str, Any]:
    return {
        "allowed": decision.allowed,
        "reason": decision.reason,
        "permission_key": decision.permission_key,
        "tenant_id": decision.tenant_id,
        "target_type": decision.target_type,
        "target_id": decision.target_id,
    }


def remember_authorization_decision(
    decision: AuthorizationDecision,
) -> AuthorizationDecision:
    _authorization_decision_ctx.set(decision)
    return decision


def get_authorization_decision() -> AuthorizationDecision | None:
    return _authorization_decision_ctx.get()


class AuthorizationService:
    def __init__(self, db: Session):
        self.db = db

    def check_permission(
        self,
        actor: User,
        tenant_id: str,
        resource: str,
        action: str,
        resource_obj: Any | None = None,
    ) -> AuthorizationDecision:
        definition = get_permission_definition(resource, action)
        target_type = type(resource_obj).__name__ if resource_obj is not None else None
        target_id = str(getattr(resource_obj, "id", "")) or None
        membership_read_mode = str(
            getattr(config, "membership_read_mode", "legacy")
        ).lower()

        def deny(reason: str) -> AuthorizationDecision:
            return remember_authorization_decision(AuthorizationDecision(
                allowed=False,
                reason=reason,
                permission_key=definition.key,
                tenant_id=tenant_id,
                target_type=target_type,
                target_id=target_id,
            ))

        if membership_read_mode not in {"legacy", "shadow", "membership"}:
            return deny("invalid_membership_read_mode")
        if (
            membership_read_mode in {"shadow", "membership"}
            and not bool(getattr(config, "membership_dual_write_enabled", False))
        ):
            return deny("membership_cutover_requires_dual_write")

        if not actor.status or actor.deleted_at is not None:
            return deny("actor_inactive")
        if definition.scope == "platform":
            return deny("platform_permission_requires_platform_pdp")
        if actor.is_platform_admin:
            return deny("platform_identity_cannot_use_tenant_rbac")
        if actor.tenant_id != tenant_id:
            return deny("actor_tenant_mismatch")

        tenant = self.db.query(Tenant).filter(Tenant.id == tenant_id).first()
        if tenant is None or not tenant.status or tenant.deleted_at is not None:
            return deny("tenant_inactive")

        if resource_obj is not None:
            resource_tenant_id = getattr(resource_obj, "tenant_id", tenant_id)
            if resource_tenant_id != tenant_id:
                return deny("resource_tenant_mismatch")
            if getattr(resource_obj, "deleted_at", None) is not None:
                return deny("resource_deleted")

        # Resource-level policy (ownership/publication/grants) must still be
        # evaluated against the current object.  The asynchronous entry point
        # adds the versioned Redis cache around this database decision.  This
        # synchronous compatibility method deliberately stays database-only;
        # calling an async Redis client from it would block or deadlock the
        # FastAPI event loop.
        membership_for_read = None
        if membership_read_mode == "membership":
            membership_for_read = (
                self.db.query(TenantMembership.id, TenantMembership.authz_version)
                .filter(
                    TenantMembership.user_id == actor.id,
                    TenantMembership.tenant_id == tenant_id,
                    TenantMembership.status.is_(True),
                )
                .first()
            )
        permission = (
            self.db.query(Permission)
            .filter(
                Permission.resource == resource,
                Permission.action == action,
            )
            .first()
        )
        if permission is None:
            return deny("permission_not_configured")

        legacy_role = (
            self.db.query(Role.id)
            .join(user_role, user_role.c.role_id == Role.id)
            .join(role_permission, role_permission.c.role_id == Role.id)
            .filter(
                user_role.c.user_id == actor.id,
                role_permission.c.permission_id == permission.id,
                Role.tenant_id == tenant_id,
                Role.status.is_(True),
            )
            .first()
        )
        active_role = legacy_role
        decision_reason = "role_permission_granted"
        if membership_read_mode in {"shadow", "membership"}:
            membership = membership_for_read
            if membership_read_mode == "shadow":
                membership = (
                    self.db.query(TenantMembership.id, TenantMembership.authz_version)
                    .filter(
                        TenantMembership.user_id == actor.id,
                        TenantMembership.tenant_id == tenant_id,
                        TenantMembership.status.is_(True),
                    )
                    .first()
                )
            staged_role = None
            if membership is not None:
                staged_role = (
                    self.db.query(Role.id)
                    .join(
                        membership_role,
                        membership_role.c.role_id == Role.id,
                    )
                    .join(
                        role_permission,
                        role_permission.c.role_id == Role.id,
                    )
                    .filter(
                        membership_role.c.membership_id == membership[0],
                        role_permission.c.permission_id == permission.id,
                        Role.tenant_id == tenant_id,
                        Role.status.is_(True),
                    )
                    .first()
                )
            legacy_allowed = legacy_role is not None
            membership_allowed = staged_role is not None
            legacy_reason = (
                "role_permission_granted"
                if legacy_allowed
                else "role_permission_missing"
            )
            membership_reason = (
                "membership_role_permission_granted"
                if membership_allowed
                else (
                    "membership_not_found"
                    if membership is None
                    else "membership_role_permission_missing"
                )
            )
            if membership_read_mode == "shadow":
                shadow_match = legacy_allowed == membership_allowed
                shadow_extra = {
                    "actor_id": str(actor.id),
                    "tenant_id": str(tenant_id),
                    "permission": definition.key,
                    "target_type": target_type,
                    "target_id": target_id,
                    "shadow_match": shadow_match,
                    "legacy_decision": {
                        "allowed": legacy_allowed,
                        "reason": legacy_reason,
                    },
                    "membership_decision": {
                        "allowed": membership_allowed,
                        "reason": membership_reason,
                    },
                }
                logger.log(
                    logging.INFO if shadow_match else logging.WARNING,
                    "authorization membership shadow decision"
                    if shadow_match
                    else "authorization membership shadow mismatch",
                    extra=shadow_extra,
                )
            else:
                active_role = staged_role
                decision_reason = "membership_role_permission_granted"

        if active_role is None:
            return deny(
                "membership_role_permission_missing"
                if membership_read_mode == "membership"
                else "role_permission_missing"
            )

        decision = AuthorizationDecision(
            allowed=True,
            reason=decision_reason,
            permission_key=definition.key,
            tenant_id=tenant_id,
            target_type=target_type,
            target_id=target_id,
        )
        return remember_authorization_decision(decision)

    async def check_permission_async(
        self,
        actor: User,
        tenant_id: str,
        resource: str,
        action: str,
        resource_obj: Any | None = None,
    ) -> AuthorizationDecision:
        """Check permission with the shared asynchronous Redis cache.

        The database remains the source of truth.  Redis is only used for the
        object-free tenant RBAC decision, and cache failures fall back to the
        synchronous database evaluation above.
        """
        membership_read_mode = str(
            getattr(config, "membership_read_mode", "legacy")
        ).lower()
        cache_key = None
        redis = None
        if resource_obj is None and membership_read_mode != "shadow":
            membership_version = 0
            if membership_read_mode == "membership":
                membership = (
                    self.db.query(TenantMembership.authz_version)
                    .filter(
                        TenantMembership.user_id == actor.id,
                        TenantMembership.tenant_id == tenant_id,
                        TenantMembership.status.is_(True),
                    )
                    .first()
                )
                membership_version = int(membership[0] or 1) if membership else 0
            cache_key = _authorization_cache_key(
                actor,
                tenant_id,
                resource,
                action,
                membership_version=membership_version,
            )
            redis = await get_redis()
            if redis is not None:
                try:
                    cached = await cache_get_json(redis, cache_key)
                    if isinstance(cached, dict) and cached.get("allowed") is True:
                        return remember_authorization_decision(
                            AuthorizationDecision(
                                allowed=True,
                                reason=str(cached["reason"]),
                                permission_key=str(cached["permission_key"]),
                                tenant_id=cached.get("tenant_id"),
                                target_type=cached.get("target_type"),
                                target_id=cached.get("target_id"),
                            )
                        )
                except Exception:  # noqa: BLE001 - fall back to the database
                    logger.warning("Authorization cache read failed", exc_info=True)

        decision = self.check_permission(
            actor,
            tenant_id,
            resource,
            action,
            resource_obj=resource_obj,
        )
        if redis is not None and cache_key is not None and decision.allowed:
            try:
                await cache_set_json(
                    redis,
                    cache_key,
                    _cache_payload(decision),
                    float(config.authz_cache_ttl_seconds),
                    jitter_seconds=2,
                )
            except Exception:  # noqa: BLE001 - cache failure must not deny access
                logger.warning("Authorization cache write failed", exc_info=True)
        return decision

    def require_permission(
        self,
        actor: User,
        tenant_id: str,
        resource: str,
        action: str,
        resource_obj: Any | None = None,
    ) -> AuthorizationDecision:
        decision = self.check_permission(
            actor,
            tenant_id,
            resource,
            action,
            resource_obj=resource_obj,
        )
        if not decision.allowed:
            raise ForbiddenException(resource, action)
        return decision

    async def require_permission_async(
        self,
        actor: User,
        tenant_id: str,
        resource: str,
        action: str,
        resource_obj: Any | None = None,
    ) -> AuthorizationDecision:
        decision = await self.check_permission_async(
            actor,
            tenant_id,
            resource,
            action,
            resource_obj=resource_obj,
        )
        if not decision.allowed:
            raise ForbiddenException(resource, action)
        return decision

    def can_assign_role(
        self,
        actor: User,
        target_role: Role,
        permission_ids: list[str] | None = None,
    ) -> bool:
        """Return whether actor may assign the target role's permission set.

        Delegation is constrained by the actor's effective permission set: a
        tenant role manager cannot mint a role with permissions they do not
        themselves possess. Tenant owners are allowed to delegate tenant
        permissions, but platform permissions remain impossible to delegate.
        """
        if not actor.status or actor.deleted_at is not None:
            return False
        if actor.tenant_id != target_role.tenant_id:
            return False

        tenant = self.db.query(Tenant).filter(Tenant.id == target_role.tenant_id).first()
        if tenant is None or not tenant.status or tenant.deleted_at is not None:
            return False

        is_owner = tenant.owner_id == actor.id
        if not is_owner:
            manager = any(
                self.check_permission(actor, actor.tenant_id, "tenant", action).allowed
                for action in ("roles_manage", "members_manage")
            )
            if not manager:
                return False

        permissions = (
            self.db.query(Permission)
            .filter(Permission.id.in_(permission_ids))
            .all()
            if permission_ids is not None
            else list(target_role.permissions)
        )
        if permission_ids is not None and {item.id for item in permissions} != set(permission_ids):
            return False

        if is_owner:
            return all(
                get_permission_definition(item.resource, item.action).scope == "tenant"
                and get_permission_definition(item.resource, item.action).is_delegable
                for item in permissions
            )

        actor_permissions = {
            f"{resource}.{action}"
            for resource, action in (
                self.db.query(Permission.resource, Permission.action)
                .join(role_permission, role_permission.c.permission_id == Permission.id)
                .join(Role, Role.id == role_permission.c.role_id)
                .filter(
                    role_permission.c.role_id.in_(
                        effective_role_ids(actor.id, actor.tenant_id)
                    ),
                    Role.tenant_id == actor.tenant_id,
                    Role.status.is_(True),
                )
                .all()
            )
        }
        try:
            return all(
                get_permission_definition(item.resource, item.action).scope == "tenant"
                and get_permission_definition(item.resource, item.action).is_delegable
                and f"{item.resource}.{item.action}" in actor_permissions
                for item in permissions
            )
        except Exception:
            return False
