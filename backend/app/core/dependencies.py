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
from app.models.user import User
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

    user_id = int(payload.get("sub", 0))
    if user_id == 0:
        raise UnauthorizedException("Invalid token payload")

    user = db.query(User).filter(User.id == user_id, User.deleted_at.is_(None)).first()
    if not user:
        raise UnauthorizedException("User not found or disabled")

    if not user.status:
        raise UnauthorizedException("User is disabled")

    # 将用户信息存入 request.state 供中间件使用
    request.state.user = user
    request.state.tenant_id = user.tenant_id

    return user


async def get_current_tenant(
    current_user: User = Depends(get_current_user),
) -> int:
    return current_user.tenant_id


def require_permission(resource: str, action: str):
    def checker(
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_session),
    ) -> User:
        for role in current_user.roles:
            if 'admin' in role.code:
                return current_user  # 管理员角色绕过权限检查
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


# 类型别名，简化路由参数声明
SessionDep = Annotated[Session, Depends(get_session)]
CurrentUser = Annotated[User, Depends(get_current_user)]
CurrentTenantId = Annotated[int, Depends(get_current_tenant)]
PlatformAdmin = Annotated[User, Depends(require_platform_admin)]
QdrantClientDep = Annotated["QdrantClient", Depends(get_qdrant_client)]
