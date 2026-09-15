from fastapi import APIRouter, Depends, Request, Query, Body
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.schemas.auth import (
    LoginForm,
    RegisterForm,
    RefreshForm,
    VerifyEmailForm,
    ResendVerifyForm,
)
from app.schemas.common import ResponseBase
from app.core.database import get_session
from app.core.dependencies import CurrentUser
from app.core.security import create_access_token, create_refresh_token, verify_password, decode_token
from app.core.exceptions import UnauthorizedException, ValidationException, BadRequestException
from app.core.redis import get_redis
from app.core.config import config
from app.models.user import User
from app.services.user import (
    register_user,
    update_last_login,
    verify_email,
    resend_verification,
    build_user_payload,
)
from app.utils.email import send_verification_email

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

    if not user.email_verified:
        raise BadRequestException("邮箱尚未验证，请先查收验证邮件完成激活")

    update_last_login(user, db)
    db.commit()

    access_token = create_access_token(user.id, user.tenant_id)
    refresh_token = create_refresh_token(user.id)

    return ResponseBase.ok(
        data={
            "access_token": access_token,
            "refresh_token": refresh_token,
            "user": build_user_payload(user, db),
        })


@router.post("/register")
def register(form_data: RegisterForm, db: Session = Depends(get_session)) -> ResponseBase:
    if form_data.password != form_data.password_repeat:
        raise ValidationException("Passwords do not match")

    try:
        user, verification_token = register_user(form_data, db)
        db.commit()
        db.refresh(user)
    except Exception:
        db.rollback()
        raise

    # 尝试发送验证邮件；未配置 SMTP 时走开发态回退（在响应中返回 token）。
    emailed = send_verification_email(user.email, verification_token)
    dev_token = verification_token if not emailed else None

    return ResponseBase.ok(
        data={
            "email_verified": False,
            "verification_token": dev_token,
            "message": "注册成功，请查收验证邮件以激活账号",
        }
    )


@router.get("/verify-email")
def verify_email_get(token: str = Query(...), db: Session = Depends(get_session)) -> ResponseBase:
    return _do_verify_email(token, db)


@router.post("/verify-email")
def verify_email_post(
    form: VerifyEmailForm, db: Session = Depends(get_session)
) -> ResponseBase:
    return _do_verify_email(form.token, db)


def _do_verify_email(token: str, db: Session) -> ResponseBase:
    """验证邮箱并激活账号；成功后直接签发令牌，用户免登录进入。"""
    try:
        user = verify_email(token, db)
        db.commit()
    except Exception:
        db.rollback()
        raise

    access_token = create_access_token(user.id, user.tenant_id)
    refresh_token = create_refresh_token(user.id)
    return ResponseBase.ok(
        data={
            "access_token": access_token,
            "refresh_token": refresh_token,
            "user": build_user_payload(user, db),
        }
    )


@router.post("/resend-verification")
def resend_verification_api(
    form: ResendVerifyForm, db: Session = Depends(get_session)
) -> ResponseBase:
    """为重发验证邮件生成新令牌。未配置 SMTP 时在响应中返回 token（开发态）。"""
    try:
        token = resend_verification(email, db)
        db.commit()
    except Exception:
        db.rollback()
        raise

    if token is None:
        # 用户不存在或已验证：出于安全不泄露差异，统一返回成功
        return ResponseBase.ok(data={"message": "若该邮箱可接收验证邮件，并已注册，请查收"})

    emailed = send_verification_email(form.email, token)
    return ResponseBase.ok(
        data={
            "verification_token": token if not emailed else None,
            "message": "验证邮件已发送，请查收",
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

    user_id = payload.get("sub", "0")
    if user_id == "0":
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
def get_me(current_user: CurrentUser, db: Session = Depends(get_session)) -> ResponseBase:
    return ResponseBase.ok(
        data=build_user_payload(current_user, db)
    )
