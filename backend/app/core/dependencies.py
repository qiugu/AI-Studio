from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, Header, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.core.vector_db import get_qdrant_client

if TYPE_CHECKING:
    from qdrant_client import QdrantClient
from app.core.security import decode_token
from app.core.exceptions import UnauthorizedException, ForbiddenException
from app.core.tenant_scope import set_tenant_scope
from app.models.user import User
from app.models.tenant import Tenant
from app.models.permission import Permission
from app.models.role_permission import role_permission
from app.models.user_role import user_role

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


async def get_current_user(
    request: Request,
    token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_session),
) -> User:
    if token is None:
        raise UnauthorizedException("Not authenticated")

    # 检查 token 黑名单（依赖 Redis，延迟导入避免循环）
    try:
        from app.core.redis import get_redis
        redis = await get_redis()
        if redis is not None:
            key = f"token_blacklist:{token}"
            if await redis.get(key):
                raise UnauthorizedException("Token has been revoked")
    except UnauthorizedException:
        raise
    except Exception:
        pass  # Redis 不可用时跳过黑名单检查

    try:
        payload = decode_token(token)
    except ValueError:
        raise UnauthorizedException("Invalid token")

    if payload.get("type") != "access":
        raise UnauthorizedException("Invalid token type")

    user_id = payload.get("sub", "0")
    if user_id == "0":
        raise UnauthorizedException("Invalid token payload")

    user = db.query(User).filter(User.id == user_id, User.deleted_at.is_(None)).first()
    if not user:
        raise UnauthorizedException("User not found or disabled")

    if not user.status:
        raise UnauthorizedException("User is disabled")

    # 将用户信息存入 request.state 供中间件使用
    # 注意：只存储需要的信息，避免 Session 关闭后访问 detached 对象
    request.state.user_id = user.id
    request.state.tenant_id = user.tenant_id

    # S3：将租户作用域注入 ContextVar，供全局查询过滤器（tenant_scope）使用。
    # 上下文随请求 Task 隔离，平台管理员（is_platform_admin）可跨租户，过滤器会据此跳过。
    set_tenant_scope(user.tenant_id, user.is_platform_admin)

    return user


async def get_current_tenant(
    current_user: User = Depends(get_current_user),
) -> str:
    return current_user.tenant_id


def require_permission(resource: str, action: str):
    def checker(
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_session),
    ) -> User:
        # 管理员角色（显式 is_admin）绕过细粒度权限检查
        if any(role.is_admin for role in current_user.roles):
            return current_user
        perm = (
            db.query(Permission)
            .select_from(Permission)
            .join(role_permission, Permission.id == role_permission.c.permission_id)
            .join(user_role, user_role.c.role_id == role_permission.c.role_id)
            .filter(user_role.c.user_id == current_user.id)
            .filter(Permission.resource == resource, Permission.action == action)
            .first()
        )
        if not perm:
            raise ForbiddenException(resource, action)
        return current_user

    return checker


async def require_platform_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    """超级管理员守卫 - 仅 is_platform_admin=True 的用户可通过。"""
    if not current_user.is_platform_admin:
        raise ForbiddenException("platform", "admin")
    return current_user


async def require_tenant_admin(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> User:
    """租户管理员守卫 - 平台管理员、租户所有者(owner_id)或拥有 admin 角色的用户可通过。"""
    if current_user.is_platform_admin:
        return current_user
    # 邮箱未验证的账户不得行使管理权限（纵深防御：login 网关已拦截其登录，此处再兜底）
    if not current_user.email_verified:
        raise ForbiddenException("tenant", "admin")
    # 租户所有者：管理能力由 owner_id 推导，与「被显式提升的 admin 角色」解耦
    tenant = (
        db.query(Tenant)
        .filter(Tenant.id == current_user.tenant_id, Tenant.owner_id == current_user.id)
        .first()
    )
    if tenant is not None:
        return current_user
    if any(role.is_admin for role in current_user.roles):
        return current_user
    raise ForbiddenException("tenant", "admin")


# 类型别名，简化路由参数声明
#
# 使用约定（三条均为踩过的坑，改动前务必确认）：
#   1. 依赖参数必须置于**签名前部**且**不带默认值**。在带默认值的参数之后再声明
#      无默认值参数会触发 Python 语法错误
#      （SyntaxError: parameter without a default follows parameter with a default）。
#   2. 不可写成 `x: TenantAdmin = None`。别名静态类型是 User / str，默认值 None
#      会被 mypy / pyright 判为 `Incompatible default for argument`。
#   3. 更不可写成 `x: TenantAdmin | None = None`。Optional 包裹 Annotated 会让
#      FastAPI 取不到 `Annotated.__metadata__` 中的 Depends，转而把 User 当作
#      请求/响应字段建模，导致应用**导入期**崩溃
#      （FastAPIError: Invalid args for response field），表现为全站 502。
#
# 正确写法：`def endpoint(_admin: TenantAdmin, tenant_id: CurrentTenantId, page: int = Query(1), ...)`
SessionDep = Annotated[Session, Depends(get_session)]
CurrentUser = Annotated[User, Depends(get_current_user)]
CurrentTenantId = Annotated[str, Depends(get_current_tenant)]
PlatformAdmin = Annotated[User, Depends(require_platform_admin)]
TenantAdmin = Annotated[User, Depends(require_tenant_admin)]
QdrantClientDep = Annotated["QdrantClient", Depends(get_qdrant_client)]
