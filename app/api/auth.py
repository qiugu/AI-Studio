from fastapi import APIRouter, Depends, Request, Query, Body
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.schemas.auth import (
    ChangePasswordForm,
    LoginForm,
    LogoutForm,
    RefreshForm,
    VerifyEmailForm,
    ResendVerifyForm,
)
from app.schemas.user import PasswordResetComplete
from app.schemas.common import ResponseBase
from app.core.database import get_session
from app.core.dependencies import CurrentUser
from app.core.security import create_access_token, create_refresh_token, verify_password, decode_token
from app.core.exceptions import (
    UnauthorizedException,
    BadRequestException,
    ForbiddenException,
    ServiceUnavailableException,
)
from app.core.redis import get_redis, token_blacklist_key
from app.models.user import User
from app.services.user import (
    update_last_login,
    verify_email,
    resend_verification,
    build_user_payload,
    complete_password_reset,
    change_my_password,
)
from app.utils.email import send_verification_email

router = APIRouter()

async def _blacklist_token(token: str) -> bool:
    """将 token 加入 Redis 黑名单。"""
    redis = await get_redis()
    if redis is None:
        raise ServiceUnavailableException("Token revocation service is unavailable")
    try:
        payload = decode_token(token)
    except ValueError:
        # 已过期或格式错误的 Token 本身不能再恢复会话，视为已完成退出。
        return True

    try:
        import time
        exp = payload.get("exp", 0)
        ttl = max(int(exp - time.time()), 1)
        await redis.setex(token_blacklist_key(token), ttl, "1")
        return True
    except Exception as exc:  # noqa: BLE001 - security state cannot silently bypass
        raise ServiceUnavailableException("Token revocation service is unavailable") from exc


async def _is_token_blacklisted(token: str) -> bool:
    """检查 token 是否在黑名单中。"""
    redis = await get_redis()
    if redis is None:
        raise ServiceUnavailableException("Token revocation service is unavailable")
    try:
        result = await redis.get(token_blacklist_key(token))
        return result is not None
    except Exception as exc:  # noqa: BLE001 - security state cannot silently bypass
        raise ServiceUnavailableException("Token revocation service is unavailable") from exc


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

    access_token = create_access_token(user.id, user.tenant_id, user.authz_version)
    refresh_token = create_refresh_token(user.id, user.credentials_version)

    return ResponseBase.ok(
        data={
            "access_token": access_token,
            "refresh_token": refresh_token,
            "user": build_user_payload(user, db),
        })


@router.post("/register")
def register() -> ResponseBase:
    raise ForbiddenException("account", "self_registration")


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

    access_token = create_access_token(user.id, user.tenant_id, user.authz_version)
    refresh_token = create_refresh_token(user.id, user.credentials_version)
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
        token = resend_verification(form.email, db)
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

    try:
        token_credentials_version = int(payload.get("credentials_version", 1))
    except (TypeError, ValueError):
        raise UnauthorizedException("Invalid refresh token payload")
    if token_credentials_version != int(user.credentials_version or 1):
        raise UnauthorizedException("Password credentials have changed")

    access_token = create_access_token(user_id, user.tenant_id, user.authz_version)

    return ResponseBase.ok(
        data={
            "access_token": access_token,
        }
    )


@router.post("/password-reset")
def complete_password_reset_api(
    data: PasswordResetComplete,
    db: Session = Depends(get_session),
) -> ResponseBase:
    user = complete_password_reset(data.token, data.password, db)
    db.commit()
    return ResponseBase.ok(data={"message": "密码已重置，请使用新密码登录"})


@router.post("/change-password")
def change_password_api(
    data: ChangePasswordForm,
    current_user: CurrentUser,
    db: Session = Depends(get_session),
) -> ResponseBase:
    change_my_password(current_user, data.current_password, data.new_password, db)
    db.commit()
    return ResponseBase.ok(data={"message": "密码已修改，请重新登录"})


@router.post("/logout")
async def logout(
    request: Request,
    current_user: CurrentUser,
    data: LogoutForm | None = None,
) -> ResponseBase:
    # Access Token 与 Refresh Token 使用不同 jti，退出时都撤销。
    token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    tokens = [token] if token else []
    if data and data.refresh_token:
        tokens.append(data.refresh_token)
    for candidate in tokens:
        await _blacklist_token(candidate)

    return ResponseBase.ok()


@router.get("/me")
def get_me(current_user: CurrentUser, db: Session = Depends(get_session)) -> ResponseBase:
    return ResponseBase.ok(
        data=build_user_payload(current_user, db)
    )
