from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.schemas.auth import RegisterForm
from app.schemas.user import UserOut
from app.models.user import User
from app.models.tenant import Tenant
from app.models.role import Role
from app.models.role_permission import role_permission
from app.models.user_role import user_role
from app.core.security import hash_password
from app.core.exceptions import ConflictException, NotFoundException
from app.services.quota import QuotaService


# 内置角色 code 常量
ROLE_TENANT_ADMIN = "tenant_admin"
ROLE_TENANT_MEMBER = "tenant_member"


def _init_builtin_roles(db: Session, tenant_id: int) -> tuple[Role, Role]:
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


def register_user(form: RegisterForm, db: Session) -> tuple[User, str, str]:
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
    tenant_id: int,
    db: Session,
    nickname: Optional[str] = None,
    check_quota: bool = True,
) -> User:
    """
    创建用户（用于租户内添加成员），创建前检查配额。
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

    # 分配默认角色 tenant_member
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


def get_user_by_id(user_id: int, tenant_id: int, db: Session) -> User:
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
