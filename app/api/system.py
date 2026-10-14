"""系统设置 API：当前租户信息与配额用量（需租户管理员权限）。"""
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.core.dependencies import CurrentTenantId, CurrentUser, require_permission
from app.schemas.admin import TenantSettingsOut, OwnerTransferRequest
from app.schemas.common import ResponseBase
from app.services.system import (
    get_tenant_settings,
    update_tenant_settings,
    transfer_tenant_owner,
)

router = APIRouter()


class TenantSelfUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


@router.get(
    "/tenant",
    response_model=ResponseBase,
    dependencies=[Depends(require_permission("tenant", "read"))],
)
def get_tenant_api(
    tenant_id: CurrentTenantId,
    db: Session = Depends(get_session),
):
    return ResponseBase.ok(data=TenantSettingsOut(**get_tenant_settings(tenant_id, db)).model_dump())


@router.put(
    "/tenant",
    response_model=ResponseBase,
    dependencies=[Depends(require_permission("tenant", "settings"))],
)
def update_tenant_api(
    tenant_id: CurrentTenantId,
    data: TenantSelfUpdate,
    db: Session = Depends(get_session),
):
    result = update_tenant_settings(tenant_id, data.model_dump(exclude_none=True), db)
    db.commit()
    return ResponseBase.ok(data=TenantSettingsOut(**result).model_dump())


@router.put(
    "/tenant/owner",
    response_model=ResponseBase,
    dependencies=[Depends(require_permission("tenant", "settings"))],
)
def transfer_tenant_owner_api(
    tenant_id: CurrentTenantId,
    data: OwnerTransferRequest,
    _owner: CurrentUser,
    db: Session = Depends(get_session),
):
    tenant = transfer_tenant_owner(
        tenant_id=tenant_id,
        target_user_id=data.target_user_id,
        current_password=data.current_password,
        actor=_owner,
        db=db,
    )
    db.commit()
    return ResponseBase.ok(data={"tenant_id": tenant.id, "owner_id": tenant.owner_id})
