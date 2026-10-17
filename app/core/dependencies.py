from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, Header, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.core.vector_db import get_qdrant_client

if TYPE_CHECKING:
    from qdrant_client import QdrantClient
from app.core.security import decode_token
from app.core.exceptions import (
    UnauthorizedException,
    ForbiddenException,
    ServiceUnavailableException,
)
from app.core.config import config
from app.core.redis import get_redis, token_blacklist_key
from app.core.tenant_scope import enable_platform_query_context, set_tenant_scope
from app.core.membership import effective_role_ids, membership_read_mode
from app.core.authorization import (
    AuthorizationDecision,
    AuthorizationService,
    remember_authorization_decision,
)
from app.core.permissions import get_permission_definition
from app.models.user import User
from app.models.role import Role
from app.models.tenant import Tenant
from app.models.user_role import user_role

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


async def get_current_user(
    request: Request,
    token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_session),
) -> User:
    if token is None:
        raise UnauthorizedException("Not authenticated")

    # Token 撤销是安全控制，Redis 不可用时不能静默放行。
    redis = await get_redis()
    if redis is None:
        raise ServiceUnavailableException("Token revocation service is unavailable")
    try:
        if await redis.get(token_blacklist_key(token)):
            raise UnauthorizedException("Token has been revoked")
    except UnauthorizedException:
        raise
    except Exception as exc:
        raise ServiceUnavailableException("Token revocation service is unavailable") from exc

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

    try:
        token_authz_version = int(payload.get("authz_version", 1))
    except (TypeError, ValueError):
        raise UnauthorizedException("Invalid token payload")
    current_authz_version = int(user.authz_version or 1)
    if token_authz_version != current_authz_version:
        raise UnauthorizedException("Authorization state has changed")

    # 将用户信息存入 request.state 供中间件使用
    # 注意：只存储需要的信息，避免 Session 关闭后访问 detached 对象
    request.state.user_id = user.id
    request.state.tenant_id = user.tenant_id

    # S3：将租户作用域注入 ContextVar，供全局查询过滤器（tenant_scope）使用。
    # 上下文随请求 Task 隔离；平台管理员默认仍处于当前租户作用域，只有通过
    # 显式平台权限守卫后才可开启跨租户查询上下文。
    request.state.tenant_scope_token = set_tenant_scope(
        user.tenant_id,
        user.is_platform_admin,
    )

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
        AuthorizationService(db).require_permission(
            current_user,
            current_user.tenant_id,
            resource,
            action,
        )
        return current_user

    return checker


def require_tenant_user(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> User:
    """租户业务接口守卫：仅允许当前租户中持有有效角色的非平台管理员。"""
    if current_user.is_platform_admin:
        raise ForbiddenException("tenant", "use")
    if membership_read_mode() not in {"legacy", "shadow", "membership"}:
        raise ForbiddenException("tenant", "membership_cutover")
    if (
        membership_read_mode() in {"shadow", "membership"}
        and not bool(getattr(config, "membership_dual_write_enabled", False))
    ):
        raise ForbiddenException("tenant", "membership_cutover")
    tenant = db.query(Tenant).filter(Tenant.id == current_user.tenant_id).first()
    if tenant is None or not tenant.status or tenant.deleted_at is not None:
        raise ForbiddenException("tenant", "use")
    if membership_read_mode() == "membership":
        has_active_role = (
            db.query(Role.id)
            .filter(
                Role.id.in_(effective_role_ids(current_user.id, current_user.tenant_id)),
                Role.tenant_id == current_user.tenant_id,
                Role.status.is_(True),
            )
            .first()
        )
    else:
        has_active_role = (
            db.query(Role.id)
            .join(user_role, user_role.c.role_id == Role.id)
            .filter(
                user_role.c.user_id == current_user.id,
                Role.tenant_id == current_user.tenant_id,
                Role.status.is_(True),
            )
            .first()
        )
    if not has_active_role:
        raise ForbiddenException("tenant", "membership")
    return current_user


async def require_platform_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    """超级管理员守卫 - 仅 is_platform_admin=True 的用户可通过。"""
    if not current_user.is_platform_admin:
        raise ForbiddenException("platform", "admin")
    return current_user


def require_platform_permission(action: str):
    """平台权限守卫；平台权限不进入租户角色，也不自动开放租户业务接口。"""
    definition = get_permission_definition("platform", action)
    if definition.scope != "platform":
        raise ValueError(f"不是平台权限: {definition.key}")

    async def checker(
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_session),
    ) -> User:
        if not current_user.is_platform_admin:
            raise ForbiddenException("platform", action)
        # 正常请求由 get_current_user 初始化 ContextVar；直接调用依赖的单测
        # 没有请求上下文时保持安全的默认作用域即可。
        try:
            enable_platform_query_context()
        except PermissionError:
            pass
        remember_authorization_decision(
            AuthorizationDecision(
                allowed=True,
                reason="platform_permission_granted",
                permission_key=definition.key,
                tenant_id=None,
            )
        )
        return current_user

    return checker


async def require_tenant_admin(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> User:
    """租户管理守卫 - 由明确的租户治理权限表达。"""
    if current_user.is_platform_admin:
        raise ForbiddenException("tenant", "admin")
    # 邮箱未验证的账户不得行使管理权限（纵深防御：login 网关已拦截其登录，此处再兜底）
    if not current_user.email_verified:
        raise ForbiddenException("tenant", "admin")
    authorization = AuthorizationService(db)
    for action in ("members_manage", "roles_manage", "settings"):
        decision = await authorization.check_permission_async(
            current_user,
            current_user.tenant_id,
            "tenant",
            action,
        )
        if decision.allowed:
            return current_user
    raise ForbiddenException("tenant", "admin")


def require_tenant_permission(action: str):
    """为租户治理 API 提供按能力拆分的守卫，避免管理权限横向扩大。"""

    async def checker(
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_session),
    ) -> User:
        if current_user.is_platform_admin or not current_user.email_verified:
            raise ForbiddenException("tenant", action)
        AuthorizationService(db).require_permission(
            current_user,
            current_user.tenant_id,
            "tenant",
            action,
        )
        return current_user

    return checker


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
PlatformTenantProvisioner = Annotated[
    User, Depends(require_platform_permission("tenant_provision"))
]
TenantAdmin = Annotated[User, Depends(require_tenant_admin)]
TenantMembersAdmin = Annotated[User, Depends(require_tenant_permission("members_manage"))]
TenantRolesAdmin = Annotated[User, Depends(require_tenant_permission("roles_manage"))]
QdrantClientDep = Annotated["QdrantClient", Depends(get_qdrant_client)]
