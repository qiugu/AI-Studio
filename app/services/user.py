from datetime import datetime, timezone, timedelta
from typing import Optional, List

import secrets
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.schemas.user import UserOut, UserUpdate, UserRoleAssign
from app.models.user import User
from app.models.tenant import Tenant
from app.models.role import Role
from app.models.email_verification import EmailVerification
from app.models.user_role import user_role
from app.core.security import hash_password
from app.core.exceptions import ConflictException, NotFoundException, ValidationException
from app.services.quota import QuotaService

from app.core.config import config


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
    return data


def create_user(
    email: str,
    password: str,
    tenant_id: str,
    db: Session,
    nickname: Optional[str] = None,
    check_quota: bool = True,
    role_ids: Optional[List[str]] = None,
) -> User:
    """
    创建用户（用于租户内添加成员），创建前检查配额。
    若指定 role_ids 则使用指定角色，否则默认分配 tenant_member。
    """
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
        _assign_roles(new_user.id, role_ids, tenant_id, db)
    else:
        member_role = _get_or_create_member_role(tenant_id, db)
        db.execute(user_role.insert().values(user_id=new_user.id, role_id=member_role.id))
        db.flush()

    return new_user


def _assign_roles(user_id: str, role_ids: List[str], tenant_id: str, db: Session) -> None:
    """全量覆盖用户角色（仅允许分配本租户内的角色）。"""
    _validate_role_ids(role_ids, tenant_id, db)
    db.execute(user_role.delete().where(user_role.c.user_id == user_id))
    for rid in set(role_ids):
        db.execute(user_role.insert().values(user_id=user_id, role_id=rid))
    db.flush()


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


def update_user(user_id: str, data: UserUpdate, tenant_id: str, db: Session) -> User:
    """更新用户信息（昵称 / 密码 / 状态）。"""
    user = get_user_by_id(user_id, tenant_id, db)
    if data.nickname is not None:
        user.nickname = data.nickname
    if data.status is not None:
        user.status = data.status
    if data.password:
        user.password_hash = hash_password(data.password)
    if "role_ids" in data.model_fields_set and data.role_ids is not None:
        _replace_user_roles(user_id, data.role_ids, tenant_id, db)
    db.flush()
    return user


def delete_user(user_id: str, tenant_id: str, db: Session) -> None:
    """软删除用户（同时清理角色关联）。"""
    user = get_user_by_id(user_id, tenant_id, db)
    db.execute(user_role.delete().where(user_role.c.user_id == user_id))
    user.deleted_at = datetime.now(timezone.utc)
    db.flush()


def assign_roles(user_id: str, data: UserRoleAssign, tenant_id: str, db: Session) -> User:
    """为用户分配角色（全量覆盖）。"""
    user = get_user_by_id(user_id, tenant_id, db)
    _replace_user_roles(user_id, data.role_ids, tenant_id, db)
    db.flush()
    return user


def _replace_user_roles(user_id: str, role_ids: List[str], tenant_id: str, db: Session) -> None:
    if not role_ids:
        member_role = _get_or_create_member_role(tenant_id, db)
        role_ids = [member_role.id]
    _validate_role_ids(role_ids, tenant_id, db)

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
    db.flush()


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
