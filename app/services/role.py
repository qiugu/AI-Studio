"""角色与权限管理服务（租户维度）。"""
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.role import Role
from app.models.permission import Permission
from app.models.user import User
from app.models.tenant import Tenant
from app.models.role_permission import role_permission
from app.models.user_role import user_role
from app.schemas.role import RoleCreate, RoleUpdate
from app.core.authorization import AuthorizationService
from app.core.exceptions import ForbiddenException, NotFoundException, ValidationException
from app.core.permissions import PERMISSION_CATALOG, is_permission_delegable
from app.services.authorization_audit import AuthorizationAuditService
from app.core.reauthentication import require_current_password
from app.models.membership_role import membership_role
from app.models.tenant_membership import TenantMembership
from app.services.membership import sync_membership_roles

import uuid


DEFAULT_MEMBER_PERMISSIONS = {
    ("knowledge", "read"),
    ("agent", "read"),
    ("agent", "chat"),
    ("workflow", "read"),
    ("workflow", "execute"),
}

# A role's ``is_admin`` flag is retained for legacy data and lifecycle
# compatibility, but an effective administration path must still retain an
# explicit tenant-governance capability.  Keep this set deliberately narrow:
# settings/audit access alone must not prevent the final member/role manager
# from being removed.
ADMIN_PERMISSION_KEYS = {
    ("tenant", "members_manage"),
    ("tenant", "roles_manage"),
}


def _lock_tenant_for_mutation(tenant_id: str, db: Session) -> Tenant:
    """Serialize role graph mutations for one tenant on row-locking databases."""
    tenant = (
        db.query(Tenant)
        .filter(Tenant.id == tenant_id)
        .with_for_update()
        .first()
    )
    if tenant is None:
        raise NotFoundException("Tenant", tenant_id)
    return tenant


def _bump_role_members(role_ids: list[str], db: Session) -> set[str]:
    if not role_ids:
        return set()
    legacy_user_ids = {
        user_id
        for (user_id,) in db.query(user_role.c.user_id)
        .filter(user_role.c.role_id.in_(role_ids))
        .distinct()
        .all()
    }
    membership_rows = (
        db.query(TenantMembership.id, TenantMembership.user_id)
        .join(
            membership_role,
            membership_role.c.membership_id == TenantMembership.id,
        )
        .filter(membership_role.c.role_id.in_(role_ids))
        .distinct()
        .all()
    )
    membership_ids = {membership_id for membership_id, _ in membership_rows}
    membership_user_ids = {user_id for _, user_id in membership_rows}
    user_ids = legacy_user_ids | membership_user_ids
    if legacy_user_ids:
        db.query(User).filter(User.id.in_(legacy_user_ids)).update(
            {User.authz_version: User.authz_version + 1},
            synchronize_session=False,
        )
    if membership_ids:
        db.query(TenantMembership).filter(
            TenantMembership.id.in_(membership_ids)
        ).update(
            {TenantMembership.authz_version: TenantMembership.authz_version + 1},
            synchronize_session=False,
        )
    return user_ids


def ensure_permission_catalog(db: Session) -> dict[tuple[str, str], Permission]:
    """Idempotently create catalog rows for fresh tenants and test databases."""
    permissions: dict[tuple[str, str], Permission] = {}
    for definition in PERMISSION_CATALOG.values():
        key = (definition.resource, definition.action)
        permission = (
            db.query(Permission)
            .filter(
                Permission.resource == definition.resource,
                Permission.action == definition.action,
            )
            .first()
        )
        if permission is None:
            permission = Permission(
                resource=definition.resource,
                action=definition.action,
                description=definition.description,
                scope=definition.scope,
                sensitivity=definition.sensitivity,
                is_delegable=definition.is_delegable,
            )
            db.add(permission)
            db.flush()
        else:
            # Keep catalog metadata authoritative for existing databases while
            # retaining unknown legacy permission rows for audit/review.
            permission.description = definition.description
            permission.scope = definition.scope
            permission.sensitivity = definition.sensitivity
            permission.is_delegable = definition.is_delegable
        permissions[key] = permission
    return permissions


def grant_default_member_permissions(role: Role, db: Session) -> None:
    """授予成员角色基础使用权限，不包含资源管理权限。"""
    permissions = ensure_permission_catalog(db)
    for key in DEFAULT_MEMBER_PERMISSIONS:
        permission = permissions[key]
        if permission not in role.permissions:
            role.permissions.append(permission)
    db.flush()


def grant_all_tenant_permissions(role: Role, db: Session) -> None:
    """授予内置租户管理员全部 tenant-scoped 权限，不包含 platform 权限。"""
    permissions = ensure_permission_catalog(db)
    for definition in PERMISSION_CATALOG.values():
        if definition.scope != "tenant":
            continue
        permission = permissions[(definition.resource, definition.action)]
        if permission not in role.permissions:
            role.permissions.append(permission)
    db.flush()


def get_role(role_id: str, tenant_id: str, db: Session) -> Role:
    role = db.query(Role).filter(Role.id == role_id, Role.tenant_id == tenant_id).first()
    if not role:
        raise NotFoundException("Role", role_id)
    return role


def list_roles(tenant_id: str, db: Session, page: int = 1, page_size: int = 100):
    query = db.query(Role).filter(Role.tenant_id == tenant_id)
    total = query.count()
    items = query.offset((page - 1) * page_size).limit(page_size).all()
    return items, total


def create_role(data: RoleCreate, tenant_id: str, db: Session, actor: User | None = None) -> Role:
    if actor is not None:
        AuthorizationService(db).require_permission(
            actor, tenant_id, "role", "create"
        )
        require_current_password(actor, data.current_password, "role_create")
    _lock_tenant_for_mutation(tenant_id, db)
    # 内置角色 code 受保护，禁止创建同名角色
    role = Role(
        tenant_id=tenant_id,
        name=data.name,
        code=f"custom_{uuid.uuid4().hex[:12]}",
        description=data.description,
        status=True,
    )
    db.add(role)
    db.flush()
    if data.permission_ids:
        set_role_permissions(
            role.id,
            data.permission_ids,
            tenant_id,
            db,
            actor=actor,
            current_password=data.current_password,
        )
    if actor is not None:
        AuthorizationAuditService(db).record_change(
            actor=actor,
            tenant_id=tenant_id,
            action="ROLE_CREATED",
            resource="role",
            target_type="Role",
            target_id=role.id,
            permission_key="role.create",
            reason="role_created",
            metadata={"permission_count": len(data.permission_ids or [])},
        )
    return role


def update_role(
    role_id: str,
    data: RoleUpdate,
    tenant_id: str,
    db: Session,
    actor: User | None = None,
    current_password: str | None = None,
) -> Role:
    _lock_tenant_for_mutation(tenant_id, db)
    role = get_role(role_id, tenant_id, db)
    if actor is not None:
        AuthorizationService(db).require_permission(
            actor, tenant_id, "role", "update", resource_obj=role
        )
        require_current_password(
            actor,
            current_password if current_password is not None else data.current_password,
            "role_update",
        )
    if data.name is not None:
        role.name = data.name
    if data.description is not None:
        role.description = data.description
    if data.status is not None:
        if role.is_admin and not data.status:
            remaining_admin_users = (
                db.query(user_role.c.user_id)
                .join(Role, Role.id == user_role.c.role_id)
                .filter(
                    Role.tenant_id == tenant_id,
                    Role.status.is_(True),
                    Role.is_admin.is_(True),
                    Role.id != role.id,
                )
                .distinct()
                .count()
            )
            if remaining_admin_users == 0:
                raise ValidationException("至少需要保留一个启用的租户管理员角色")
        role.status = data.status
        _bump_role_members([role.id], db)
    if actor is not None:
        AuthorizationAuditService(db).record_change(
            actor=actor,
            tenant_id=tenant_id,
            action="ROLE_UPDATED",
            resource="role",
            target_type="Role",
            target_id=role.id,
            permission_key="role.update",
            reason="role_updated",
            metadata={"status": data.status} if data.status is not None else {},
        )
    db.flush()
    return role


def delete_role(
    role_id: str,
    tenant_id: str,
    db: Session,
    actor: User | None = None,
    current_password: str | None = None,
) -> None:
    _lock_tenant_for_mutation(tenant_id, db)
    role = get_role(role_id, tenant_id, db)
    if actor is not None:
        AuthorizationService(db).require_permission(
            actor, tenant_id, "role", "delete", resource_obj=role
        )
        require_current_password(actor, current_password, "role_delete")
    # 保证租户始终保留一个可用的管理员角色，避免误删导致租户失控。
    if role.is_admin:
        remaining_admin_roles = (
            db.query(Role)
            .filter(
                Role.tenant_id == tenant_id,
                Role.status.is_(True),
                Role.is_admin.is_(True),
                Role.id != role.id,
            )
            .count()
        )
        if remaining_admin_roles == 0:
            raise ValidationException("至少需要保留一个启用的租户管理员角色")

    # 保护内置管理员角色，避免误删导致租户失控
    if role.code.startswith("tenant_admin"):
        raise ValidationException("内置管理员角色不可删除")
    if actor is not None:
        AuthorizationAuditService(db).record_change(
            actor=actor,
            tenant_id=tenant_id,
            action="ROLE_DELETED",
            resource="role",
            target_type="Role",
            target_id=role.id,
            permission_key="role.delete",
            reason="role_deleted",
            metadata={"role_code": role.code},
        )
    affected_user_ids = _bump_role_members([role.id], db)
    db.execute(membership_role.delete().where(membership_role.c.role_id == role.id))
    db.execute(role_permission.delete().where(role_permission.c.role_id == role_id))
    db.delete(role)
    db.flush()
    for user_id in affected_user_ids:
        sync_membership_roles(user_id, tenant_id, db)


def set_role_permissions(
    role_id: str,
    permission_ids: List[str],
    tenant_id: str,
    db: Session,
    actor: User | None = None,
    current_password: str | None = None,
) -> Role:
    _lock_tenant_for_mutation(tenant_id, db)
    role = get_role(role_id, tenant_id, db)
    perms = db.query(Permission).filter(Permission.id.in_(permission_ids)).all()
    valid_ids = {p.id for p in perms}
    if valid_ids != set(permission_ids):
        raise ValidationException("存在无效的权限 ID")
    for permission in perms:
        if not is_permission_delegable(permission.resource, permission.action):
            raise ValidationException(
                f"权限不可委派给租户角色: {permission.resource}.{permission.action}"
            )

    # Check the caller before evaluating lifecycle invariants so an actor who
    # cannot manage roles does not learn whether this is the final admin path.
    if actor is not None and not AuthorizationService(db).can_assign_role(
        actor, role, permission_ids
    ):
        raise ForbiddenException("role", "permissions_manage")
    if actor is not None:
        require_current_password(actor, current_password, "role_permissions_manage")

    current_has_admin_path = role.is_admin or (
        db.query(Permission.id)
        .join(role_permission, role_permission.c.permission_id == Permission.id)
        .filter(
            role_permission.c.role_id == role.id,
            Permission.resource == "tenant",
            Permission.action.in_([action for _resource, action in ADMIN_PERMISSION_KEYS]),
        )
        .first()
        is not None
    )
    new_has_admin_path = any(
        (permission.resource, permission.action) in ADMIN_PERMISSION_KEYS
        for permission in perms
    )
    if current_has_admin_path and not new_has_admin_path:
        other_admin_path = (
            db.query(Role.id)
            .outerjoin(role_permission, role_permission.c.role_id == Role.id)
            .outerjoin(Permission, Permission.id == role_permission.c.permission_id)
            .filter(
                Role.tenant_id == tenant_id,
                Role.status.is_(True),
                Role.id != role.id,
            )
            .filter(
                Role.is_admin.is_(True)
                | (
                    (Permission.resource == "tenant")
                    & Permission.action.in_(
                        [action for _resource, action in ADMIN_PERMISSION_KEYS]
                    )
                )
            )
            .first()
        )
        if other_admin_path is None:
            raise ValidationException("至少需要保留一个启用的租户管理员路径")
    _bump_role_members([role_id], db)
    db.execute(role_permission.delete().where(role_permission.c.role_id == role_id))
    for pid in valid_ids:
        db.execute(role_permission.insert().values(role_id=role_id, permission_id=pid))
    if actor is not None:
        AuthorizationAuditService(db).record_change(
            actor=actor,
            tenant_id=tenant_id,
            action="ROLE_PERMISSIONS_CHANGED",
            resource="role",
            target_type="Role",
            target_id=role.id,
            permission_key="role.permissions_manage",
            reason="role_permissions_replaced",
            metadata={"permission_ids": sorted(valid_ids)},
        )
    db.flush()
    return role


def list_permissions(db: Session) -> List[Permission]:
    permissions = ensure_permission_catalog(db)
    return [
        permissions[(definition.resource, definition.action)]
        for definition in PERMISSION_CATALOG.values()
        if definition.is_delegable
    ]
