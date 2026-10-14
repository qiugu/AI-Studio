"""用户管理 API（租户维度，需租户管理员权限）。"""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.core.dependencies import CurrentTenantId, require_permission
from app.schemas.user import (
    UserOut,
    UserCreate,
    UserUpdate,
    UserRoleAssign,
    PasswordResetRequest,
)
from app.schemas.common import ResponseBase, PaginatedData, ReauthRequest
from app.services.user import (
    create_user,
    list_users,
    get_user_by_id,
    update_user,
    delete_user,
    assign_roles,
    request_password_reset,
)
from app.utils.email import send_password_reset_email

router = APIRouter()


@router.get(
    "",
    response_model=ResponseBase,
    dependencies=[Depends(require_permission("user", "read"))],
)
def list_users_api(
    tenant_id: CurrentTenantId,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    search: Optional[str] = Query(None),
    status: Optional[bool] = Query(None),
    db: Session = Depends(get_session),
):
    items, total = list_users(
        tenant_id, db, page=page, page_size=page_size, search=search, status=status
    )
    return ResponseBase.ok(
        data=PaginatedData(
            items=[UserOut.model_validate(u) for u in items],
            total=total,
            page=page,
            page_size=page_size,
        ).model_dump()
    )


@router.post(
    "",
    response_model=ResponseBase,
    dependencies=[Depends(require_permission("user", "create"))],
)
def create_user_api(
    tenant_id: CurrentTenantId,
    data: UserCreate,
    _admin=Depends(require_permission("user", "create")),
    db: Session = Depends(get_session),
):
    user = create_user(
        email=data.email,
        password=data.password,
        tenant_id=tenant_id,
        db=db,
        nickname=data.nickname,
        role_ids=data.role_ids,
        actor=_admin,
    )
    db.commit()
    db.refresh(user)
    return ResponseBase.ok(data=UserOut.model_validate(user).model_dump())


@router.get(
    "/{user_id}",
    response_model=ResponseBase,
    dependencies=[Depends(require_permission("user", "read"))],
)
def get_user_api(
    tenant_id: CurrentTenantId,
    user_id: str,
    db: Session = Depends(get_session),
):
    user = get_user_by_id(user_id, tenant_id, db)
    return ResponseBase.ok(data=UserOut.model_validate(user).model_dump())


@router.put(
    "/{user_id}",
    response_model=ResponseBase,
    dependencies=[Depends(require_permission("user", "update"))],
)
def update_user_api(
    tenant_id: CurrentTenantId,
    user_id: str,
    data: UserUpdate,
    _admin=Depends(require_permission("user", "update")),
    db: Session = Depends(get_session),
):
    user = update_user(user_id, data, tenant_id, db, actor=_admin)
    db.commit()
    db.refresh(user)
    return ResponseBase.ok(data=UserOut.model_validate(user).model_dump())


@router.post(
    "/{user_id}/password-reset",
    response_model=ResponseBase,
    dependencies=[Depends(require_permission("user", "update"))],
)
def request_password_reset_api(
    tenant_id: CurrentTenantId,
    user_id: str,
    data: PasswordResetRequest,
    _admin=Depends(require_permission("user", "update")),
    db: Session = Depends(get_session),
):
    user, token = request_password_reset(
        user_id,
        tenant_id,
        db,
        actor=_admin,
        current_password=data.current_password,
    )
    emailed = send_password_reset_email(user.email, token)
    db.commit()
    return ResponseBase.ok(
        data={
            "email_sent": emailed,
            "message": (
                "密码重置邮件已发送，请让用户通过邮件设置新密码"
                if emailed
                else "密码重置请求已创建，但邮件服务未配置，暂时无法发送重置链接"
            ),
        }
    )


@router.delete(
    "/{user_id}",
    response_model=ResponseBase,
    dependencies=[Depends(require_permission("user", "delete"))],
)
def delete_user_api(
    tenant_id: CurrentTenantId,
    user_id: str,
    data: ReauthRequest,
    _admin=Depends(require_permission("user", "delete")),
    db: Session = Depends(get_session),
):
    delete_user(
        user_id,
        tenant_id,
        db,
        actor=_admin,
        current_password=data.current_password,
    )
    db.commit()
    return ResponseBase.ok()


@router.post(
    "/{user_id}/roles",
    response_model=ResponseBase,
    dependencies=[Depends(require_permission("user", "roles_manage"))],
)
def assign_roles_api(
    tenant_id: CurrentTenantId,
    user_id: str,
    data: UserRoleAssign,
    _admin=Depends(require_permission("user", "roles_manage")),
    db: Session = Depends(get_session),
):
    user = assign_roles(user_id, data, tenant_id, db, actor=_admin)
    db.commit()
    db.refresh(user)
    return ResponseBase.ok(data=UserOut.model_validate(user).model_dump())
