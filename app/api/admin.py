"""平台管理 API：仅创建租户并授予首位租户管理员。"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.core.dependencies import PlatformAdmin
from app.schemas.admin import TenantCreate
from app.schemas.common import ResponseBase
from app.services.admin import create_tenant

router = APIRouter()


@router.post("/tenants", response_model=ResponseBase)
def create_tenant_api(
    _admin: PlatformAdmin,
    data: TenantCreate,
    db: Session = Depends(get_session),
):
    tenant = create_tenant(data.model_dump(), db)
    db.commit()
    db.refresh(tenant)
    return ResponseBase.ok(
        data={"tenant_id": tenant.id, "admin_email": data.admin_email, "message": "租户及首位管理员创建成功"}
    )
