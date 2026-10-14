"""平台管理 API：仅创建租户并授予首位租户管理员。"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.core.dependencies import PlatformTenantProvisioner, require_platform_permission
from app.schemas.admin import TenantCreate
from app.schemas.common import ResponseBase
from app.services.admin import create_tenant
from app.schemas.plugin import PluginCreate, PluginUpdate, PluginOut
from app.schemas.ai_model import AIModelCreate, AIModelUpdate, AIModelOut
from app.services.plugin import PluginService
from app.services.ai_model import AIModelService
from app.core.exceptions import ForbiddenException
from app.models.user import User

router = APIRouter()


@router.post("/tenants", response_model=ResponseBase)
def create_tenant_api(
    _admin: PlatformTenantProvisioner,
    data: TenantCreate,
    db: Session = Depends(get_session),
):
    tenant = create_tenant(data.model_dump(), db)
    db.commit()
    db.refresh(tenant)
    return ResponseBase.ok(
        data={"tenant_id": tenant.id, "admin_email": data.admin_email, "message": "租户及首位管理员创建成功"}
    )


def _require_public_plugin(plugin):
    if plugin.tenant_id is not None or not plugin.is_public:
        raise ForbiddenException("plugin", "public_plugin_manage")


@router.post(
    "/public-plugins",
    response_model=ResponseBase,
)
def create_public_plugin(
    data: PluginCreate,
    _admin: User = Depends(require_platform_permission("public_plugin_manage")),
    db: Session = Depends(get_session),
):
    service = PluginService(
        db=db,
        tenant_id=_admin.tenant_id,
        is_platform_admin=True,
    )
    plugin = service.create(data.model_copy(update={"is_public": True}))
    db.commit()
    db.refresh(plugin)
    return ResponseBase.ok(data=PluginOut.model_validate(plugin).model_dump())


@router.put(
    "/public-plugins/{plugin_id}",
    response_model=ResponseBase,
)
def update_public_plugin(
    plugin_id: str,
    data: PluginUpdate,
    _admin: User = Depends(require_platform_permission("public_plugin_manage")),
    db: Session = Depends(get_session),
):
    service = PluginService(
        db=db,
        tenant_id=_admin.tenant_id,
        is_platform_admin=True,
    )
    plugin = service.get(plugin_id)
    _require_public_plugin(plugin)
    plugin = service.update(plugin_id, data.model_copy(update={"is_public": True}))
    db.commit()
    db.refresh(plugin)
    return ResponseBase.ok(data=PluginOut.model_validate(plugin).model_dump())


@router.delete(
    "/public-plugins/{plugin_id}",
    response_model=ResponseBase,
)
def delete_public_plugin(
    plugin_id: str,
    _admin: User = Depends(require_platform_permission("public_plugin_manage")),
    db: Session = Depends(get_session),
):
    service = PluginService(
        db=db,
        tenant_id=_admin.tenant_id,
        is_platform_admin=True,
    )
    plugin = service.get(plugin_id)
    _require_public_plugin(plugin)
    service.delete(plugin_id)
    db.commit()
    return ResponseBase.ok()


@router.post(
    "/public-models",
    response_model=ResponseBase,
)
def create_public_model(
    data: AIModelCreate,
    _admin: User = Depends(require_platform_permission("public_model_manage")),
    db: Session = Depends(get_session),
):
    service = AIModelService(
        db,
        _admin.tenant_id,
        is_platform_admin=True,
    )
    model = service.create_public(data)
    db.commit()
    db.refresh(model)
    return ResponseBase.ok(data=AIModelOut.model_validate(model).model_dump())


@router.put(
    "/public-models/{model_id}",
    response_model=ResponseBase,
)
def update_public_model(
    model_id: str,
    data: AIModelUpdate,
    _admin: User = Depends(require_platform_permission("public_model_manage")),
    db: Session = Depends(get_session),
):
    service = AIModelService(
        db,
        _admin.tenant_id,
        is_platform_admin=True,
    )
    model = service.get(model_id)
    if model.tenant_id is not None:
        raise ForbiddenException("ai_model", "public_model_manage")
    model = service.update(model_id, data)
    db.commit()
    db.refresh(model)
    return ResponseBase.ok(data=AIModelOut.model_validate(model).model_dump())


@router.delete(
    "/public-models/{model_id}",
    response_model=ResponseBase,
)
def delete_public_model(
    model_id: str,
    _admin: User = Depends(require_platform_permission("public_model_manage")),
    db: Session = Depends(get_session),
):
    service = AIModelService(
        db,
        _admin.tenant_id,
        is_platform_admin=True,
    )
    model = service.get(model_id)
    if model.tenant_id is not None:
        raise ForbiddenException("ai_model", "public_model_manage")
    service.delete(model_id)
    db.commit()
    return ResponseBase.ok()
