from datetime import datetime, timezone
from typing import Optional, List

from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.schemas.auth import RegisterForm
from app.schemas.user import UserOut, UserUpdate, UserRoleAssign
from app.models.user import User
from app.models.tenant import Tenant
from app.models.role import Role
from app.models.role_permission import role_permission
from app.models.user_role import user_role
from app.core.security import hash_password
from app.core.exceptions import ConflictException, NotFoundException, ValidationException
from app.services.quota import QuotaService

import uuid


# 内置角色 code 常量
ROLE_TENANT_ADMIN = "tenant_admin"
ROLE_TENANT_MEMBER = "tenant_member"


def _init_builtin_roles(db: Session, tenant_id: str) -> tuple[Role, Role]:
    """初始化租户内置角色：tenant_admin 和 tenant_member。"""
    admin_role = Role(
        tenant_id=tenant_id,
        name="租户管理员",
        code=f"{ROLE_TENANT_ADMIN}_{tenant_id}",
        description="租户管理员，拥有租户内所有权限",
    )
    member_role = Role(
        tenant_id=tenant_id,
        name="租户成员",
        code=f"{ROLE_TENANT_MEMBER}_{tenant_id}",
        description="租户普通成员",
    )
    db.add(admin_role)
    db.add(member_role)
    db.flush()

    # 将 knowledge 相关权限绑定到内置角色
    from app.models.permission import Permission
    knowledge_perms = (
        db.query(Permission)
        .filter(Permission.resource == "knowledge")
        .all()
    )
    if knowledge_perms:
        for perm in knowledge_perms:
            db.execute(role_permission.insert().values(role_id=admin_role.id, permission_id=perm.id))
            db.execute(role_permission.insert().values(role_id=member_role.id, permission_id=perm.id))
        db.flush()

    return admin_role, member_role


def register_user(form: RegisterForm, db: Session) -> User:
    """
    原子事务注册：
    1. 检查邮箱唯一性
    2. 创建租户
    3. 创建用户
    4. 初始化内置角色 tenant_admin / tenant_member
    5. 将用户分配为 tenant_admin
    返回 (user, access_token, refresh_token)
    """
    existing = db.query(User).filter(User.email == form.email).first()
    if existing:
        raise ConflictException("Email already registered")

    # 创建租户（租户名默认使用邮箱前缀）
    tenant_name = form.nickname or form.email.split("@")[0]
    tenant = Tenant(
        name=tenant_name,
        description=f"Tenant for {form.email}",
        plan="free",
        max_users=10,
        max_models=5,
        is_system_init=True,
    )
    db.add(tenant)
    db.flush()  # 获取 tenant.id

    # 创建用户
    new_user = User(
        email=form.email,
        password_hash=hash_password(form.password),
        nickname=form.nickname,
        tenant_id=tenant.id,
    )
    db.add(new_user)
    db.flush()  # 获取 user.id

    # 初始化内置角色
    admin_role, _ = _init_builtin_roles(db, tenant.id)

    # 将用户分配为 tenant_admin
    db.execute(user_role.insert().values(user_id=new_user.id, role_id=admin_role.id))
    db.flush()

    return new_user


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

    new_user = User(
        email=email,
        password_hash=hash_password(password),
        nickname=nickname,
        tenant_id=tenant_id,
    )
    db.add(new_user)
    db.flush()

    # 角色分配：优先使用指定角色，否则默认 tenant_member
    if role_ids:
        _assign_roles(new_user.id, role_ids, tenant_id, db)
    else:
        member_role = (
            db.query(Role)
            .filter(
                Role.tenant_id == tenant_id,
                Role.code == f"{ROLE_TENANT_MEMBER}_{tenant_id}",
            )
            .first()
        )
        if member_role:
            db.execute(user_role.insert().values(user_id=new_user.id, role_id=member_role.id))
            db.flush()

    return new_user


def _assign_roles(user_id: str, role_ids: List[str], tenant_id: str, db: Session) -> None:
    """全量覆盖用户角色（仅允许分配本租户内的角色）。"""
    roles = db.query(Role).filter(Role.tenant_id == tenant_id, Role.id.in_(role_ids)).all()
    valid_ids = {r.id for r in roles}
    db.execute(user_role.delete().where(user_role.c.user_id == user_id))
    for rid in valid_ids:
        db.execute(user_role.insert().values(user_id=user_id, role_id=rid))
    db.flush()


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
    _assign_roles(user_id, data.role_ids, tenant_id, db)
    db.flush()
    return user


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
