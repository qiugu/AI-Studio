"""角色与权限管理 API（租户维度，需租户管理员权限）。"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.core.dependencies import CurrentTenantId, require_permission
from app.core.exceptions import ValidationException
from app.core.permissions import get_permission_definition
from app.schemas.role import RoleOut, RoleCreate, RoleUpdate, RolePermissionAssign, PermissionOut
from app.schemas.common import ResponseBase, PaginatedData, ReauthRequest
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


def _permission_payload(permission) -> dict:
    payload = PermissionOut.model_validate(permission).model_dump()
    try:
        definition = get_permission_definition(permission.resource, permission.action)
    except ValidationException:
        # 未知存量权限保留展示，但不能继续被前端误认为可委派目录项。
        payload.update(
            key=f"{permission.resource}.{permission.action}",
            scope="unknown",
            sensitivity="high",
            is_delegable=False,
        )
    else:
        payload.update(
            key=definition.key,
            scope=definition.scope,
            sensitivity=definition.sensitivity,
            is_delegable=definition.is_delegable,
        )
    return payload


def _role_payload(role) -> dict:
    payload = RoleOut.model_validate(role).model_dump()
    payload["permissions"] = [
        _permission_payload(permission) for permission in role.permissions
    ]
    return payload


@router.get(
    "",
    response_model=ResponseBase,
    dependencies=[Depends(require_permission("role", "read"))],
)
def list_roles_api(
    tenant_id: CurrentTenantId,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=200),
    db: Session = Depends(get_session),
):
    items, total = list_roles(tenant_id, db, page=page, page_size=page_size)
    return ResponseBase.ok(
        data=PaginatedData(
            items=[_role_payload(r) for r in items],
            total=total,
            page=page,
            page_size=page_size,
        ).model_dump()
    )


@router.post(
    "",
    response_model=ResponseBase,
    dependencies=[Depends(require_permission("role", "create"))],
)
def create_role_api(
    tenant_id: CurrentTenantId,
    data: RoleCreate,
    _admin=Depends(require_permission("role", "create")),
    db: Session = Depends(get_session),
):
    role = create_role(data, tenant_id, db, actor=_admin)
    db.commit()
    db.refresh(role)
    return ResponseBase.ok(data=_role_payload(role))


@router.get(
    "/{role_id}",
    response_model=ResponseBase,
    dependencies=[Depends(require_permission("role", "read"))],
)
def get_role_api(
    tenant_id: CurrentTenantId,
    role_id: str,
    db: Session = Depends(get_session),
):
    role = get_role(role_id, tenant_id, db)
    return ResponseBase.ok(data=_role_payload(role))


@router.put(
    "/{role_id}",
    response_model=ResponseBase,
    dependencies=[Depends(require_permission("role", "update"))],
)
def update_role_api(
    tenant_id: CurrentTenantId,
    role_id: str,
    data: RoleUpdate,
    _admin=Depends(require_permission("role", "update")),
    db: Session = Depends(get_session),
):
    role = update_role(role_id, data, tenant_id, db, actor=_admin)
    db.commit()
    db.refresh(role)
    return ResponseBase.ok(data=_role_payload(role))


@router.delete(
    "/{role_id}",
    response_model=ResponseBase,
    dependencies=[Depends(require_permission("role", "delete"))],
)
def delete_role_api(
    tenant_id: CurrentTenantId,
    role_id: str,
    data: ReauthRequest,
    _admin=Depends(require_permission("role", "delete")),
    db: Session = Depends(get_session),
):
    delete_role(role_id, tenant_id, db, actor=_admin, current_password=data.current_password)
    db.commit()
    return ResponseBase.ok()


@router.get(
    "/permissions/all",
    response_model=ResponseBase,
    dependencies=[Depends(require_permission("role", "read"))],
)
def list_permissions_api(
    tenant_id: CurrentTenantId,
    db: Session = Depends(get_session),
):
    perms = list_permissions(db)
    return ResponseBase.ok(data=[_permission_payload(p) for p in perms])


@router.put(
    "/{role_id}/permissions",
    response_model=ResponseBase,
    dependencies=[Depends(require_permission("role", "permissions_manage"))],
)
def set_role_permissions_api(
    tenant_id: CurrentTenantId,
    role_id: str,
    data: RolePermissionAssign,
    _admin=Depends(require_permission("role", "permissions_manage")),
    db: Session = Depends(get_session),
):
    role = set_role_permissions(
        role_id,
        data.permission_ids,
        tenant_id,
        db,
        actor=_admin,
        current_password=data.current_password,
    )
    db.commit()
    db.refresh(role)
    return ResponseBase.ok(data=_role_payload(role))
