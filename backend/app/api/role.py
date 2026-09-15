"""角色与权限管理 API（租户维度，需租户管理员权限）。"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.core.dependencies import CurrentTenantId, TenantAdmin
from app.schemas.role import RoleOut, RoleCreate, RoleUpdate, RolePermissionAssign, PermissionOut
from app.schemas.common import ResponseBase, PaginatedData
from app.services.role import (
    list_roles,
    create_role,
    update_role,
    delete_role,
    set_role_permissions,
    list_permissions,
    get_role,
)

router = APIRouter()


@router.get("", response_model=ResponseBase)
def list_roles_api(
    _admin: TenantAdmin,
    tenant_id: CurrentTenantId,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=200),
    db: Session = Depends(get_session),
):
    items, total = list_roles(tenant_id, db, page=page, page_size=page_size)
    return ResponseBase.ok(
        data=PaginatedData(
            items=[RoleOut.model_validate(r) for r in items],
            total=total,
            page=page,
            page_size=page_size,
        ).model_dump()
    )


@router.post("", response_model=ResponseBase)
def create_role_api(
    _admin: TenantAdmin,
    tenant_id: CurrentTenantId,
    data: RoleCreate,
    db: Session = Depends(get_session),
):
    role = create_role(data, tenant_id, db)
    db.commit()
    db.refresh(role)
    return ResponseBase.ok(data=RoleOut.model_validate(role).model_dump())


@router.get("/{role_id}", response_model=ResponseBase)
def get_role_api(
    _admin: TenantAdmin,
    tenant_id: CurrentTenantId,
    role_id: str,
    db: Session = Depends(get_session),
):
    role = get_role(role_id, tenant_id, db)
    return ResponseBase.ok(data=RoleOut.model_validate(role).model_dump())


@router.put("/{role_id}", response_model=ResponseBase)
def update_role_api(
    _admin: TenantAdmin,
    tenant_id: CurrentTenantId,
    role_id: str,
    data: RoleUpdate,
    db: Session = Depends(get_session),
):
    role = update_role(role_id, data, tenant_id, db)
    db.commit()
    db.refresh(role)
    return ResponseBase.ok(data=RoleOut.model_validate(role).model_dump())


@router.delete("/{role_id}", response_model=ResponseBase)
def delete_role_api(
    _admin: TenantAdmin,
    tenant_id: CurrentTenantId,
    role_id: str,
    db: Session = Depends(get_session),
):
    delete_role(role_id, tenant_id, db)
    db.commit()
    return ResponseBase.ok()


@router.get("/permissions/all", response_model=ResponseBase)
def list_permissions_api(
    _admin: TenantAdmin,
    tenant_id: CurrentTenantId,
    db: Session = Depends(get_session),
):
    perms = list_permissions(db)
    return ResponseBase.ok(data=[PermissionOut.model_validate(p).model_dump() for p in perms])


@router.put("/{role_id}/permissions", response_model=ResponseBase)
def set_role_permissions_api(
    _admin: TenantAdmin,
    tenant_id: CurrentTenantId,
    role_id: str,
    data: RolePermissionAssign,
    db: Session = Depends(get_session),
):
    role = set_role_permissions(role_id, data.permission_ids, tenant_id, db)
    db.commit()
    db.refresh(role)
    return ResponseBase.ok(data=RoleOut.model_validate(role).model_dump())
