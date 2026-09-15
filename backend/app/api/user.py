"""用户管理 API（租户维度，需租户管理员权限）。"""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.core.dependencies import CurrentTenantId, TenantAdmin
from app.schemas.user import UserOut, UserCreate, UserUpdate, UserRoleAssign
from app.schemas.common import ResponseBase, PaginatedData
from app.services.user import (
    create_user,
    list_users,
    get_user_by_id,
    update_user,
    delete_user,
    assign_roles,
)

router = APIRouter()


@router.get("", response_model=ResponseBase)
def list_users_api(
    _admin: TenantAdmin,
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


@router.post("", response_model=ResponseBase)
def create_user_api(
    _admin: TenantAdmin,
    tenant_id: CurrentTenantId,
    data: UserCreate,
    db: Session = Depends(get_session),
):
    user = create_user(
        email=data.email,
        password=data.password,
        tenant_id=tenant_id,
        db=db,
        nickname=data.nickname,
        role_ids=data.role_ids,
    )
    db.commit()
    db.refresh(user)
    return ResponseBase.ok(data=UserOut.model_validate(user).model_dump())


@router.get("/{user_id}", response_model=ResponseBase)
def get_user_api(
    _admin: TenantAdmin,
    tenant_id: CurrentTenantId,
    user_id: str,
    db: Session = Depends(get_session),
):
    user = get_user_by_id(user_id, tenant_id, db)
    return ResponseBase.ok(data=UserOut.model_validate(user).model_dump())


@router.put("/{user_id}", response_model=ResponseBase)
def update_user_api(
    _admin: TenantAdmin,
    tenant_id: CurrentTenantId,
    user_id: str,
    data: UserUpdate,
    db: Session = Depends(get_session),
):
    user = update_user(user_id, data, tenant_id, db)
    db.commit()
    db.refresh(user)
    return ResponseBase.ok(data=UserOut.model_validate(user).model_dump())


@router.delete("/{user_id}", response_model=ResponseBase)
def delete_user_api(
    _admin: TenantAdmin,
    tenant_id: CurrentTenantId,
    user_id: str,
    db: Session = Depends(get_session),
):
    delete_user(user_id, tenant_id, db)
    db.commit()
    return ResponseBase.ok()


@router.post("/{user_id}/roles", response_model=ResponseBase)
def assign_roles_api(
    _admin: TenantAdmin,
    tenant_id: CurrentTenantId,
    user_id: str,
    data: UserRoleAssign,
    db: Session = Depends(get_session),
):
    user = assign_roles(user_id, data, tenant_id, db)
    db.commit()
    db.refresh(user)
    return ResponseBase.ok(data=UserOut.model_validate(user).model_dump())
