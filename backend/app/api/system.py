"""系统设置 API：当前租户信息与配额用量（需租户管理员权限）。"""
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.core.dependencies import CurrentTenantId, TenantAdmin, CurrentUser
from app.schemas.admin import TenantSettingsOut
from app.schemas.common import ResponseBase
from app.services.system import get_tenant_settings, update_tenant_settings

router = APIRouter()


class TenantSelfUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


@router.get("/tenant", response_model=ResponseBase)
def get_tenant_api(
    tenant_id: CurrentTenantId = None,
    db: Session = Depends(get_session),
    _admin: TenantAdmin = None,
):
    return ResponseBase.ok(data=TenantSettingsOut(**get_tenant_settings(tenant_id, db)).model_dump())


@router.put("/tenant", response_model=ResponseBase)
def update_tenant_api(
    data: TenantSelfUpdate,
    tenant_id: CurrentTenantId = None,
    db: Session = Depends(get_session),
    _admin: TenantAdmin = None,
):
    result = update_tenant_settings(tenant_id, data.model_dump(exclude_none=True), db)
    db.commit()
    return ResponseBase.ok(data=TenantSettingsOut(**result).model_dump())
