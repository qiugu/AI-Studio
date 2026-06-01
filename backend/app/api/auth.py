from fastapi import APIRouter, Depends, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.schemas.auth import LoginForm, RegisterForm, RefreshForm
from app.schemas.user import UserOut
from app.schemas.common import ResponseBase
from app.core.database import get_session
from app.core.dependencies import CurrentUser
from app.core.security import create_access_token, create_refresh_token, verify_password, decode_token
from app.core.exceptions import UnauthorizedException, ValidationException, BadRequestException
from app.core.redis import get_redis
from app.models.user import User
from app.services.user import register_user, update_last_login

router = APIRouter()

# Token 黑名单 Redis key 前缀
_TOKEN_BLACKLIST_PREFIX = "token_blacklist:"
_TOKEN_BLACKLIST_TTL = 60 * 60 * 24 * 7  # 7 天


async def _blacklist_token(token: str) -> None:
    """将 token 加入 Redis 黑名单。"""
    redis = await get_redis()
    if redis is not None:
        try:
            payload = decode_token(token)
            import time
            exp = payload.get("exp", 0)
            ttl = max(int(exp - time.time()), 1)
            await redis.setex(f"{_TOKEN_BLACKLIST_PREFIX}{token}", ttl, "1")
        except Exception:
            pass


async def _is_token_blacklisted(token: str) -> bool:
    """检查 token 是否在黑名单中。"""
    redis = await get_redis()
    if redis is None:
        return False
    result = await redis.get(f"{_TOKEN_BLACKLIST_PREFIX}{token}")
    return result is not None


_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


@router.post("/login")
async def login(form_data: LoginForm, db: Session = Depends(get_session)) -> ResponseBase:
    user = db.query(User).filter(User.email == form_data.email, User.deleted_at.is_(None)).first()
    if not user or not verify_password(form_data.password, user.password_hash):
        raise BadRequestException("Invalid email or password")

    if not user.status:
        raise BadRequestException("User is disabled")

    update_last_login(user, db)
    db.commit()

    access_token = create_access_token(user.id, user.tenant_id)
    refresh_token = create_refresh_token(user.id)

    return ResponseBase.ok(
        data={
            "access_token": access_token,
            "refresh_token": refresh_token,
            "user": UserOut.model_validate(user).model_dump(),
        })


@router.post("/register")
def register(form_data: RegisterForm, db: Session = Depends(get_session)) -> ResponseBase:
    if form_data.password != form_data.password_repeat:
        raise ValidationException("Passwords do not match")

    try:
        user = register_user(form_data, db)
        db.commit()
        db.refresh(user)
    except Exception:
        db.rollback()
        raise

    access_token = create_access_token(user.id, user.tenant_id)
    refresh_token = create_refresh_token(user.id)

    return ResponseBase.ok(
        data={
            "access_token": access_token,
            "refresh_token": refresh_token,
            "user": UserOut.model_validate(user).model_dump(),
        }
    )


@router.post("/refresh")
async def refresh(
    form_data: RefreshForm,
    db: Session = Depends(get_session),
) -> ResponseBase:
    token = form_data.refresh_token

    # 检查黑名单
    if await _is_token_blacklisted(token):
        raise UnauthorizedException("Token has been revoked")

    try:
        payload = decode_token(token)
    except ValueError:
        raise UnauthorizedException("Invalid refresh token")

    if payload.get("type") != "refresh":
        raise UnauthorizedException("Invalid token type")

    user_id = int(payload.get("sub", 0))
    if user_id == 0:
        raise UnauthorizedException("Invalid token payload")

    # 验证用户是否还存在且有效
    user = db.query(User).filter(User.id == user_id, User.deleted_at.is_(None), User.status.is_(True)).first()
    if not user:
        raise UnauthorizedException("User not found or disabled")

    access_token = create_access_token(user_id, user.tenant_id)

    return ResponseBase.ok(
        data={
            "access_token": access_token,
        }
    )


@router.post("/logout")
async def logout(
    request: Request,
    current_user: CurrentUser,
) -> ResponseBase:
    # 将 access token 加入黑名单
    token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if token:
        await _blacklist_token(token)

    return ResponseBase.ok()


@router.get("/me")
def get_me(current_user: CurrentUser) -> ResponseBase:
    return ResponseBase.ok(
        data=UserOut.model_validate(current_user).model_dump()
    )
