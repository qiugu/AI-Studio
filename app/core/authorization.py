"""Centralized tenant-aware authorization decisions."""
from dataclasses import dataclass
from contextvars import ContextVar
from collections import OrderedDict
import logging
from threading import RLock
from time import monotonic
from typing import Any

from sqlalchemy.orm import Session

from app.core.exceptions import ForbiddenException
from app.core.config import config
from app.core.permissions import get_permission_definition
from app.core.membership import effective_role_ids
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

# The authorization service is synchronous because it runs alongside the
# SQLAlchemy Session.  Keep this cache local and bounded instead of calling the
# async Redis client from a synchronous request path.  The user authz_version
# is part of the key, so supported role/member mutations invalidate old
# entries without requiring a cross-process cache delete.
_authorization_allow_cache: OrderedDict[
    tuple[str, str, int, str, str, str, int], tuple[float, AuthorizationDecision]
] = OrderedDict()
_authorization_cache_lock = RLock()


def clear_authorization_cache() -> None:
    """Clear local positive authorization decisions.

    Primarily useful for process lifecycle hooks and deterministic tests.  A
    normal authorization change relies on ``User.authz_version`` instead.
    """
    with _authorization_cache_lock:
        _authorization_allow_cache.clear()


def _authorization_cache_key(
    actor: User,
    tenant_id: str,
    resource: str,
    action: str,
    membership_version: int = 0,
) -> tuple[str, str, int, str, str, str, int]:
    return (
        str(actor.id),
        str(tenant_id),
        int(actor.authz_version or 1),
        resource,
        action,
        str(getattr(config, "membership_read_mode", "legacy")),
        int(membership_version),
    )


def _get_cached_allow(
    key: tuple[str, str, int, str, str, str, int],
) -> AuthorizationDecision | None:
    now = monotonic()
    with _authorization_cache_lock:
        cached = _authorization_allow_cache.get(key)
        if cached is None:
            return None
        expires_at, decision = cached
        if expires_at <= now:
            _authorization_allow_cache.pop(key, None)
            return None
        _authorization_allow_cache.move_to_end(key)
        return remember_authorization_decision(decision)


def _cache_allow(
    key: tuple[str, str, int, str, str, str, int],
    decision: AuthorizationDecision,
) -> None:
    ttl = float(config.authz_cache_ttl_seconds)
    if ttl <= 0:
        return
    max_entries = max(1, int(config.authz_cache_max_entries))
    with _authorization_cache_lock:
        _authorization_allow_cache[key] = (monotonic() + ttl, decision)
        _authorization_allow_cache.move_to_end(key)
        while len(_authorization_allow_cache) > max_entries:
            _authorization_allow_cache.popitem(last=False)


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
        # evaluated against the current object.  Cache only the tenant RBAC
        # decision for object-free checks; the versioned key prevents stale
        # grants after supported role/member mutations.
        cache_key = None
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
        if resource_obj is None and membership_read_mode != "shadow":
            cache_key = _authorization_cache_key(
                actor,
                tenant_id,
                resource,
                action,
                membership_version=(
                    int(membership_for_read[1] or 1)
                    if membership_for_read is not None
                    else 0
                ),
            )
            cached = _get_cached_allow(cache_key)
            if cached is not None:
                return cached

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
        if cache_key is not None:
            _cache_allow(cache_key, decision)
        return remember_authorization_decision(decision)

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
