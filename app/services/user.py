from datetime import datetime, timezone, timedelta
from typing import Optional, List

import hashlib
import secrets
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.schemas.user import RoleOut, UserOut, UserUpdate, UserRoleAssign
from app.models.user import User
from app.models.tenant import Tenant
from app.models.role import Role
from app.models.email_verification import EmailVerification
from app.models.password_reset import PasswordResetToken
from app.models.user_role import user_role
from app.core.security import hash_password
from app.core.authorization import AuthorizationService
from app.core.exceptions import (
    ConflictException,
    ForbiddenException,
    NotFoundException,
    ValidationException,
)
from app.services.quota import QuotaService

from app.core.config import config
from app.core.membership import effective_role_ids, membership_read_mode
from app.services.authorization_audit import AuthorizationAuditService
from app.core.reauthentication import require_current_password
from app.services.membership import (
    deactivate_membership,
    sync_membership_roles,
)


# 内置角色 code 常量
ROLE_TENANT_MEMBER = "tenant_member"


def _generate_verification_token() -> str:
    return secrets.token_urlsafe(32)


def create_email_verification(user: User, db: Session) -> str:
    """为用户生成邮箱验证令牌；同一用户旧令牌先失效。返回新令牌。"""
    db.query(EmailVerification).filter(EmailVerification.user_id == user.id).delete()
    token = _generate_verification_token()
    record = EmailVerification(
        user_id=user.id,
        token=token,
        expires_at=datetime.now(timezone.utc)
        + timedelta(hours=config.email_verification_ttl_hours),
    )
    db.add(record)
    db.flush()
    return token


def verify_email(token: str, db: Session) -> User:
    """消费验证令牌，将用户标记为已验证。令牌无效或过期则抛错。"""
    record = (
        db.query(EmailVerification)
        .filter(EmailVerification.token == token)
        .first()
    )
    if not record:
        raise ValidationException("无效的验证链接")
    # MySQL DateTime 不存时区，读回为 naive；用 naive UTC 比较，避免 aware/naive 冲突
    now = datetime.utcnow()
    if record.expires_at < now:
        db.delete(record)
        db.flush()
        raise ValidationException("验证链接已过期，请重新发送")

    user = db.query(User).filter(User.id == record.user_id).first()
    if not user:
        raise NotFoundException("用户不存在")
    user.email_verified = True
    db.delete(record)
    db.flush()
    return user


def resend_verification(email: str, db: Session) -> Optional[str]:
    """为重发验证邮件生成新令牌；用户不存在或已验证则返回 None。"""
    user = db.query(User).filter(User.email == email).first()
    if not user or user.email_verified:
        return None
    return create_email_verification(user, db)


def _password_reset_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _utc_now_naive() -> datetime:
    """Return UTC without tzinfo for MySQL DateTime columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def request_password_reset(
    user_id: str,
    tenant_id: str,
    db: Session,
    *,
    actor: User,
    current_password: str,
) -> tuple[User, str]:
    """创建一次性重置令牌；永不接收或生成管理员指定的新密码。"""
    user = get_user_by_id(user_id, tenant_id, db)
    AuthorizationService(db).require_permission(
        actor, tenant_id, "user", "update", resource_obj=user
    )
    require_current_password(actor, current_password, "user_password_reset")

    now = _utc_now_naive()
    db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user.id,
        PasswordResetToken.used_at.is_(None),
    ).update({PasswordResetToken.used_at: now}, synchronize_session=False)

    raw_token = secrets.token_urlsafe(32)
    db.add(
        PasswordResetToken(
            tenant_id=tenant_id,
            user_id=user.id,
            requested_by=actor.id,
            token_hash=_password_reset_token_hash(raw_token),
            expires_at=now + timedelta(hours=1),
        )
    )
    AuthorizationAuditService(db).record_change(
        actor=actor,
        tenant_id=tenant_id,
        action="USER_PASSWORD_RESET_REQUESTED",
        resource="user",
        target_type="User",
        target_id=user.id,
        permission_key="user.update",
        reason="user_password_reset_requested",
        metadata={
            "target_user_id": user.id,
            "target_email": user.email,
            "delivery": "email",
        },
    )
    db.flush()
    return user, raw_token


def complete_password_reset(token: str, new_password: str, db: Session) -> User:
    """消费一次性令牌并撤销目标用户的既有认证会话。"""
    now = _utc_now_naive()
    reset_record = (
        db.query(PasswordResetToken)
        .filter(
            PasswordResetToken.token_hash == _password_reset_token_hash(token),
            PasswordResetToken.used_at.is_(None),
            PasswordResetToken.expires_at > now,
        )
        .with_for_update()
        .first()
    )
    if reset_record is None:
        raise ValidationException("密码重置链接无效或已过期")

    user = (
        db.query(User)
        .filter(
            User.id == reset_record.user_id,
            User.tenant_id == reset_record.tenant_id,
            User.deleted_at.is_(None),
        )
        .with_for_update()
        .first()
    )
    if user is None:
        raise ValidationException("密码重置链接无效或已过期")

    user.password_hash = hash_password(new_password)
    user.authz_version = int(user.authz_version or 1) + 1
    user.credentials_version = int(user.credentials_version or 1) + 1
    reset_record.used_at = now
    db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user.id,
        PasswordResetToken.used_at.is_(None),
        PasswordResetToken.id != reset_record.id,
    ).update({PasswordResetToken.used_at: now}, synchronize_session=False)
    AuthorizationAuditService(db).record_change(
        actor=None,
        tenant_id=user.tenant_id,
        action="USER_PASSWORD_RESET_COMPLETED",
        resource="user",
        target_type="User",
        target_id=user.id,
        permission_key="user.update",
        reason="user_password_reset_completed",
        metadata={
            "target_user_id": user.id,
            "target_email": user.email,
            "credentials_revoked": True,
        },
    )
    db.flush()
    return user


def change_my_password(
    user: User,
    current_password: str,
    new_password: str,
    db: Session,
) -> User:
    """修改当前用户自己的密码，并撤销其既有认证会话。"""
    require_current_password(user, current_password, "self_password_change")
    user.password_hash = hash_password(new_password)
    user.authz_version = int(user.authz_version or 1) + 1
    user.credentials_version = int(user.credentials_version or 1) + 1
    now = _utc_now_naive()
    db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user.id,
        PasswordResetToken.used_at.is_(None),
    ).update({PasswordResetToken.used_at: now}, synchronize_session=False)
    AuthorizationAuditService(db).record_change(
        actor=user,
        tenant_id=user.tenant_id,
        action="USER_PASSWORD_CHANGED",
        resource="user",
        target_type="User",
        target_id=user.id,
        permission_key="auth.change_password",
        reason="self_password_changed",
        metadata={
            "target_user_id": user.id,
            "target_email": user.email,
            "credential_change": "self_service",
            "credentials_revoked": True,
        },
    )
    db.flush()
    return user


def build_user_payload(user: User, db: Session) -> dict:
    """序列化用户为接口响应体，并补上 ``is_tenant_owner``（owner_id 推导）。"""
    from app.models.tenant import Tenant

    data = UserOut.model_validate(user).model_dump()
    is_owner = (
        db.query(Tenant)
        .filter(Tenant.id == user.tenant_id, Tenant.owner_id == user.id)
        .first()
        is not None
    )
    data["is_tenant_owner"] = is_owner
    # Keep the role summary and capability snapshot on the same authorization
    # read path.  During the staged membership cutover, reading ``user.roles``
    # here would expose legacy capabilities even though the PDP enforces the
    # staged membership_roles graph.
    current_read_mode = membership_read_mode()
    if current_read_mode == "membership":
        if bool(getattr(config, "membership_dual_write_enabled", False)):
            role_ids = effective_role_ids(user.id, user.tenant_id)
            effective_roles = (
                db.query(Role)
                .filter(
                    Role.id.in_(role_ids),
                    Role.tenant_id == user.tenant_id,
                    Role.status.is_(True),
                )
                .all()
            )
        else:
            # The PDP fail-closes this invalid rollout combination.  Return an
            # empty snapshot as well so /me cannot advertise stale authority.
            effective_roles = []
    elif current_read_mode == "shadow":
        if bool(getattr(config, "membership_dual_write_enabled", False)):
            # Shadow mode still enforces the legacy graph; keep the snapshot
            # aligned with that effective decision source.
            role_ids = effective_role_ids(user.id, user.tenant_id)
            effective_roles = (
                db.query(Role)
                .filter(
                    Role.id.in_(role_ids),
                    Role.tenant_id == user.tenant_id,
                    Role.status.is_(True),
                )
                .all()
            )
        else:
            effective_roles = []
    elif current_read_mode == "legacy":
        role_ids = effective_role_ids(user.id, user.tenant_id)
        effective_roles = (
            db.query(Role)
            .filter(
                Role.id.in_(role_ids),
                Role.tenant_id == user.tenant_id,
                Role.status.is_(True),
            )
            .all()
        )
    else:
        effective_roles = []
    data["roles"] = [RoleOut.model_validate(role).model_dump() for role in effective_roles]
    capabilities = {
        f"{permission.resource}.{permission.action}"
        for role in effective_roles
        for permission in role.permissions
    }
    if user.is_platform_admin:
        capabilities.add("platform.tenant_provision")
    data["capabilities"] = sorted(capabilities)
    return data


def create_user(
    email: str,
    password: str,
    tenant_id: str,
    db: Session,
    nickname: Optional[str] = None,
    check_quota: bool = True,
    role_ids: Optional[List[str]] = None,
    actor: Optional[User] = None,
) -> User:
    """
    创建用户（用于租户内添加成员），创建前检查配额。
    若指定 role_ids 则使用指定角色，否则默认分配 tenant_member。
    """
    if actor is not None:
        AuthorizationService(db).require_permission(
            actor, tenant_id, "user", "create"
        )
    if check_quota:
        QuotaService(db).check_user_quota(tenant_id)

    existing = db.query(User).filter(User.email == email).first()
    if existing:
        raise ConflictException("Email already registered")

    if role_ids:
        _validate_role_ids(role_ids, tenant_id, db)

    new_user = User(
        email=email,
        password_hash=hash_password(password),
        nickname=nickname,
        tenant_id=tenant_id,
        email_verified=True,
    )
    db.add(new_user)
    db.flush()

    # 角色分配：优先使用指定角色，否则默认 tenant_member。
    # 空数组也视为未指定，避免前端未选择角色时生成无角色用户。
    if role_ids:
        _assign_roles(new_user.id, role_ids, tenant_id, db, actor=actor)
    else:
        member_role = _get_or_create_member_role(tenant_id, db)
        db.execute(user_role.insert().values(user_id=new_user.id, role_id=member_role.id))
        db.flush()
        sync_membership_roles(
            new_user.id,
            tenant_id,
            db,
            role_ids=[member_role.id],
        )

    if actor is not None:
        AuthorizationAuditService(db).record_change(
            actor=actor,
            tenant_id=tenant_id,
            action="USER_CREATED",
            resource="user",
            target_type="User",
            target_id=new_user.id,
            permission_key="user.create",
            reason="user_created",
            metadata={"role_ids": sorted(role_ids or [])},
        )

    return new_user


def _assign_roles(
    user_id: str,
    role_ids: List[str],
    tenant_id: str,
    db: Session,
    actor: Optional[User] = None,
) -> None:
    """全量覆盖用户角色（仅允许分配本租户内的角色）。"""
    _validate_role_ids(role_ids, tenant_id, db)
    _ensure_actor_can_assign_roles(actor, role_ids, tenant_id, db)
    db.execute(user_role.delete().where(user_role.c.user_id == user_id))
    for rid in set(role_ids):
        db.execute(user_role.insert().values(user_id=user_id, role_id=rid))
    db.flush()
    sync_membership_roles(user_id, tenant_id, db, role_ids=role_ids)


def _validate_role_ids(role_ids: List[str], tenant_id: str, db: Session) -> None:
    """校验角色全部属于当前租户，避免非法 ID 被静默丢弃。"""
    roles = (
        db.query(Role)
        .filter(
            Role.tenant_id == tenant_id,
            Role.status.is_(True),
            Role.id.in_(role_ids),
        )
        .all()
    )
    valid_ids = {r.id for r in roles}
    if valid_ids != set(role_ids):
        raise ValidationException("存在不属于当前租户的角色")


def _get_or_create_member_role(tenant_id: str, db: Session) -> Role:
    """返回租户默认成员角色，并兼容缺少内置角色的存量租户。"""
    member_role = (
        db.query(Role)
        .filter(
            Role.tenant_id == tenant_id,
            Role.code == f"{ROLE_TENANT_MEMBER}_{tenant_id}",
        )
        .first()
    )
    if member_role:
        if not member_role.status:
            raise ValidationException("租户成员角色已停用，无法创建普通成员")
        return member_role
    # 存量租户可能已有管理员角色但缺少成员角色，不能重复创建唯一 code 的管理员角色。
    member_role = Role(
        tenant_id=tenant_id,
        name="租户成员",
        code=f"{ROLE_TENANT_MEMBER}_{tenant_id}",
        description="租户普通成员",
    )
    db.add(member_role)
    db.flush()

    from app.services.role import grant_default_member_permissions
    grant_default_member_permissions(member_role, db)
    return member_role


def list_users(
    tenant_id: str,
    db: Session,
    page: int = 1,
    page_size: int = 20,
    search: Optional[str] = None,
    status: Optional[bool] = None,
):
    """列出租户内用户（分页 + 搜索 + 状态筛选）。"""
    query = db.query(User).filter(User.tenant_id == tenant_id, User.deleted_at.is_(None))
    if search:
        like = f"%{search}%"
        query = query.filter(or_(User.email.like(like), User.nickname.like(like)))
    if status is not None:
        query = query.filter(User.status == status)
    total = query.count()
    items = (
        query.order_by(User.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return items, total


def update_user(
    user_id: str,
    data: UserUpdate,
    tenant_id: str,
    db: Session,
    actor: Optional[User] = None,
) -> User:
    """更新用户资料（昵称 / 状态 / 角色），密码必须走独立重置流程。"""
    if data.password:
        raise ValidationException("管理员不能直接设置用户密码，请发起密码重置")
    if actor is not None:
        authorization = AuthorizationService(db)
        authorization.require_permission(actor, tenant_id, "user", "update")
    tenant_query = db.query(Tenant).filter(Tenant.id == tenant_id)
    # Acquire the tenant lock before reading the target for status mutations;
    # otherwise a concurrent delete/deactivation could leave this session
    # holding a stale user snapshot when it finally checks the admin invariant.
    tenant = (
        tenant_query.with_for_update().first()
        if data.status is not None
        else tenant_query.first()
    )
    user = get_user_by_id(user_id, tenant_id, db)
    nickname_before = user.nickname
    lifecycle_change = data.status is not None and data.status != user.status
    is_owner = tenant is not None and tenant.owner_id == user.id
    if is_owner and data.status is False:
        raise ValidationException("租户所有者必须先完成所有权转移")
    if data.status is False and data.status != user.status:
        _ensure_not_last_active_admin_user(user, tenant_id, db)
    if actor is not None and data.status is False and data.status != user.status:
        AuthorizationService(db).require_permission(
            actor, tenant_id, "user", "delete", resource_obj=user
        )
    if actor is not None and "role_ids" in data.model_fields_set:
        AuthorizationService(db).require_permission(
            actor, tenant_id, "user", "roles_manage", resource_obj=user
        )
    if actor is not None and (
        (data.status is not None and data.status != user.status)
        or "role_ids" in data.model_fields_set
    ):
        require_current_password(actor, data.current_password, "user_update")
    if data.nickname is not None:
        user.nickname = data.nickname
    if data.status is not None and data.status != user.status:
        user.status = data.status
        user.authz_version = int(user.authz_version or 1) + 1
        if data.status:
            sync_membership_roles(user_id, tenant_id, db)
        else:
            deactivate_membership(user_id, tenant_id, db)
    if "role_ids" in data.model_fields_set and data.role_ids is not None:
        _replace_user_roles(user_id, data.role_ids, tenant_id, db, actor=actor)
    if actor is not None:
        AuthorizationAuditService(db).record_change(
            actor=actor,
            tenant_id=tenant_id,
            action="USER_UPDATED",
            resource="user",
            target_type="User",
            target_id=user.id,
            permission_key="user.update",
            reason="user_updated",
            metadata={
                "status_changed": data.status is not None,
                "roles_changed": "role_ids" in data.model_fields_set,
                "nickname_changed": data.nickname is not None and data.nickname != nickname_before,
                "target_user_id": user.id,
                "target_email": user.email,
                "nickname_before": nickname_before,
                "nickname_after": user.nickname,
            },
        )
    db.flush()
    return user


def delete_user(
    user_id: str,
    tenant_id: str,
    db: Session,
    actor: Optional[User] = None,
    current_password: str | None = None,
) -> None:
    """软删除用户（同时清理角色关联）。"""
    if actor is not None:
        AuthorizationService(db).require_permission(
            actor, tenant_id, "user", "delete"
        )
        require_current_password(actor, current_password, "user_delete")
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).with_for_update().first()
    user = get_user_by_id(user_id, tenant_id, db)
    if tenant is not None and tenant.owner_id == user.id:
        raise ValidationException("租户所有者必须先完成所有权转移")
    _ensure_not_last_active_admin_user(user, tenant_id, db)
    db.execute(user_role.delete().where(user_role.c.user_id == user_id))
    user.deleted_at = datetime.now(timezone.utc)
    user.authz_version = int(user.authz_version or 1) + 1
    deactivate_membership(user_id, tenant_id, db)
    if actor is not None:
        AuthorizationAuditService(db).record_change(
            actor=actor,
            tenant_id=tenant_id,
            action="USER_DELETED",
            resource="user",
            target_type="User",
            target_id=user.id,
            permission_key="user.delete",
            reason="user_deleted",
        )
    db.flush()


def assign_roles(
    user_id: str,
    data: UserRoleAssign,
    tenant_id: str,
    db: Session,
    actor: Optional[User] = None,
    current_password: str | None = None,
) -> User:
    """为用户分配角色（全量覆盖）。"""
    if actor is not None:
        AuthorizationService(db).require_permission(
            actor, tenant_id, "user", "roles_manage"
        )
        require_current_password(actor, current_password, "user_roles_manage")
    user = get_user_by_id(user_id, tenant_id, db)
    _replace_user_roles(user_id, data.role_ids, tenant_id, db, actor=actor)
    if actor is not None:
        AuthorizationAuditService(db).record_change(
            actor=actor,
            tenant_id=tenant_id,
            action="USER_ROLES_CHANGED",
            resource="user",
            target_type="User",
            target_id=user.id,
            permission_key="user.roles_manage",
            reason="user_roles_replaced",
            metadata={"role_ids": sorted(data.role_ids)},
        )
    db.flush()
    return user


def _replace_user_roles(
    user_id: str,
    role_ids: List[str],
    tenant_id: str,
    db: Session,
    actor: Optional[User] = None,
) -> None:
    db.query(Tenant).filter(Tenant.id == tenant_id).with_for_update().first()
    if not role_ids:
        member_role = _get_or_create_member_role(tenant_id, db)
        role_ids = [member_role.id]
    _validate_role_ids(role_ids, tenant_id, db)
    _ensure_actor_can_assign_roles(actor, role_ids, tenant_id, db)

    current_admin = (
        db.query(Role.id)
        .join(user_role, user_role.c.role_id == Role.id)
        .filter(
            user_role.c.user_id == user_id,
            Role.tenant_id == tenant_id,
            Role.status.is_(True),
            Role.is_admin.is_(True),
        )
        .first()
    )
    new_admin = db.query(Role.id).filter(
        Role.id.in_(role_ids),
        Role.tenant_id == tenant_id,
        Role.status.is_(True),
        Role.is_admin.is_(True),
    ).first()
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if tenant is not None and tenant.owner_id == user_id and not new_admin:
        raise ValidationException("租户所有者必须保留管理员角色")
    if current_admin and not new_admin:
        active_admin_users = (
            db.query(user_role.c.user_id)
            .select_from(user_role)
            .join(Role, Role.id == user_role.c.role_id)
            .filter(
                Role.tenant_id == tenant_id,
                Role.status.is_(True),
                Role.is_admin.is_(True),
            )
            .distinct()
            .count()
        )
        if active_admin_users <= 1:
            raise ValidationException("租户至少需要保留一个管理员角色")

    db.execute(user_role.delete().where(user_role.c.user_id == user_id))
    for role_id in set(role_ids):
        db.execute(user_role.insert().values(user_id=user_id, role_id=role_id))
    db.query(User).filter(User.id == user_id).update(
        {User.authz_version: User.authz_version + 1},
        synchronize_session=False,
    )
    db.flush()
    sync_membership_roles(user_id, tenant_id, db, role_ids=role_ids)


def _ensure_not_last_active_admin_user(
    user: User,
    tenant_id: str,
    db: Session,
) -> None:
    """Prevent lifecycle mutations from removing the final admin subject.

    Callers must lock the tenant row before invoking this check so concurrent
    user deletion/deactivation/role replacement operations for one tenant are
    serialized on databases that support row-level locks.
    """
    if not user.status or user.deleted_at is not None:
        return

    is_admin = (
        db.query(Role.id)
        .join(user_role, user_role.c.role_id == Role.id)
        .filter(
            user_role.c.user_id == user.id,
            Role.tenant_id == tenant_id,
            Role.status.is_(True),
            Role.is_admin.is_(True),
        )
        .first()
    )
    if is_admin is None:
        return

    active_admin_users = (
        db.query(user_role.c.user_id)
        .select_from(user_role)
        .join(User, User.id == user_role.c.user_id)
        .join(Role, Role.id == user_role.c.role_id)
        .filter(
            User.tenant_id == tenant_id,
            User.status.is_(True),
            User.deleted_at.is_(None),
            Role.tenant_id == tenant_id,
            Role.status.is_(True),
            Role.is_admin.is_(True),
        )
        .distinct()
        .count()
    )
    if active_admin_users <= 1:
        raise ValidationException("至少需要保留一个启用的租户管理员用户")


def _ensure_actor_can_assign_roles(
    actor: Optional[User], role_ids: List[str], tenant_id: str, db: Session
) -> None:
    if actor is None:
        return
    authorization = AuthorizationService(db)
    roles = db.query(Role).filter(Role.id.in_(role_ids), Role.tenant_id == tenant_id).all()
    for role in roles:
        if not authorization.can_assign_role(actor, role):
            raise ForbiddenException("user", "roles_manage")


def get_user_by_id(user_id: str, tenant_id: str, db: Session) -> User:
    user = (
        db.query(User)
        .filter(User.id == user_id, User.tenant_id == tenant_id, User.deleted_at.is_(None))
        .first()
    )
    if not user:
        raise NotFoundException("User", user_id)
    return user


def update_last_login(user: User, db: Session) -> None:
    user.last_login_at = datetime.now(timezone.utc)
    db.flush()
