"""插件系统 API"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.core.dependencies import CurrentUser, CurrentTenantId, require_tenant_admin
from app.schemas.plugin import (
    PluginCreate,
    PluginUpdate,
    PluginOut,
    PluginEndpointCreate,
    PluginEndpointUpdate,
    PluginEndpointOut,
    PluginConfigUpdateRequest,
    PluginTestRequest,
)
from app.schemas.common import ResponseBase, PaginatedData
from app.services.plugin import PluginService

router = APIRouter(dependencies=[Depends(require_tenant_admin)])


def _svc(db: Session, tenant_id: str, current_user: CurrentUser) -> PluginService:
    return PluginService(
        db=db,
        tenant_id=tenant_id,
        is_platform_admin=bool(current_user.is_platform_admin),
    )


@router.get("", response_model=ResponseBase)
def list_plugins(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    include_public: bool = Query(True, description="是否包含平台公共插件"),
    plugin_type: str | None = Query(None, description="能力形态过滤：tool/connector/processor"),
    source_type: str | None = Query(None, description="接入方式过滤：http/mcp/skill"),
    status: str | None = Query(None),
    tenant_id: CurrentTenantId = None,
    db: Session = Depends(get_session),
    _current_user: CurrentUser = None,
):
    svc = _svc(db, tenant_id, _current_user)
    items, total = svc.list(
        page=page,
        page_size=page_size,
        include_public=include_public,
        plugin_type=plugin_type,
        source_type=source_type,
        status=status,
    )
    return ResponseBase.ok(
        data=PaginatedData(
            items=[PluginOut.model_validate(p).model_dump() for p in items],
            total=total,
            page=page,
            page_size=page_size,
        ).model_dump()
    )


@router.post("", response_model=ResponseBase)
def create_plugin(
    data: PluginCreate,
    tenant_id: CurrentTenantId = None,
    db: Session = Depends(get_session),
    _current_user: CurrentUser = None,
):
    svc = _svc(db, tenant_id, _current_user)
    plugin = svc.create(data)
    db.commit()
    db.refresh(plugin)
    return ResponseBase.ok(data=PluginOut.model_validate(plugin).model_dump())


@router.get("/{plugin_id}", response_model=ResponseBase)
def get_plugin(
    plugin_id: str,
    tenant_id: CurrentTenantId = None,
    db: Session = Depends(get_session),
    _current_user: CurrentUser = None,
):
    svc = _svc(db, tenant_id, _current_user)
    plugin = svc.get(plugin_id)
    endpoints = getattr(plugin, "_endpoints", [])
    return ResponseBase.ok(
        data=PluginOut.from_orm_with_endpoints(plugin, endpoints).model_dump()
    )


@router.put("/{plugin_id}", response_model=ResponseBase)
def update_plugin(
    plugin_id: str,
    data: PluginUpdate,
    tenant_id: CurrentTenantId = None,
    db: Session = Depends(get_session),
    _current_user: CurrentUser = None,
):
    svc = _svc(db, tenant_id, _current_user)
    plugin = svc.update(plugin_id, data)
    db.commit()
    db.refresh(plugin)
    return ResponseBase.ok(data=PluginOut.model_validate(plugin).model_dump())


@router.delete("/{plugin_id}", response_model=ResponseBase)
def delete_plugin(
    plugin_id: str,
    tenant_id: CurrentTenantId = None,
    db: Session = Depends(get_session),
    _current_user: CurrentUser = None,
):
    svc = _svc(db, tenant_id, _current_user)
    svc.delete(plugin_id)
    db.commit()
    return ResponseBase.ok()


@router.post("/{plugin_id}/test", response_model=ResponseBase)
def test_plugin(
    plugin_id: str,
    data: PluginTestRequest = None,
    tenant_id: CurrentTenantId = None,
    db: Session = Depends(get_session),
    _current_user: CurrentUser = None,
):
    svc = _svc(db, tenant_id, _current_user)
    result = svc.test(plugin_id, data or PluginTestRequest())
    return ResponseBase.ok(data=result.model_dump())


@router.get("/{plugin_id}/endpoints", response_model=ResponseBase)
def list_endpoints(
    plugin_id: str,
    tenant_id: CurrentTenantId = None,
    db: Session = Depends(get_session),
    _current_user: CurrentUser = None,
):
    svc = _svc(db, tenant_id, _current_user)
    endpoints = svc.list_endpoints(plugin_id)
    return ResponseBase.ok(
        data=[PluginEndpointOut.model_validate(e).model_dump() for e in endpoints]
    )


@router.post("/{plugin_id}/endpoints", response_model=ResponseBase)
def add_endpoint(
    plugin_id: str,
    data: PluginEndpointCreate,
    tenant_id: CurrentTenantId = None,
    db: Session = Depends(get_session),
    _current_user: CurrentUser = None,
):
    svc = _svc(db, tenant_id, _current_user)
    endpoint = svc.add_endpoint(plugin_id, data)
    db.commit()
    db.refresh(endpoint)
    return ResponseBase.ok(data=PluginEndpointOut.model_validate(endpoint).model_dump())


@router.post("/{plugin_id}/endpoints/import", response_model=ResponseBase)
def import_endpoints(
    plugin_id: str,
    tenant_id: CurrentTenantId = None,
    db: Session = Depends(get_session),
    _current_user: CurrentUser = None,
):
    svc = _svc(db, tenant_id, _current_user)
    count = svc.import_endpoints_from_spec(plugin_id)
    db.commit()
    return ResponseBase.ok(
        data={"imported": count}, message=f"已导入 {count} 个端点"
    )


@router.put("/{plugin_id}/endpoints/{ep_id}", response_model=ResponseBase)
def update_endpoint(
    plugin_id: str,
    ep_id: str,
    data: PluginEndpointUpdate,
    tenant_id: CurrentTenantId = None,
    db: Session = Depends(get_session),
    _current_user: CurrentUser = None,
):
    svc = _svc(db, tenant_id, _current_user)
    endpoint = svc.update_endpoint(plugin_id, ep_id, data)
    db.commit()
    db.refresh(endpoint)
    return ResponseBase.ok(data=PluginEndpointOut.model_validate(endpoint).model_dump())


@router.delete("/{plugin_id}/endpoints/{ep_id}", response_model=ResponseBase)
def delete_endpoint(
    plugin_id: str,
    ep_id: str,
    tenant_id: CurrentTenantId = None,
    db: Session = Depends(get_session),
    _current_user: CurrentUser = None,
):
    svc = _svc(db, tenant_id, _current_user)
    svc.delete_endpoint(plugin_id, ep_id)
    db.commit()
    return ResponseBase.ok()


@router.get("/{plugin_id}/config", response_model=ResponseBase)
def get_config(
    plugin_id: str,
    tenant_id: CurrentTenantId = None,
    db: Session = Depends(get_session),
    _current_user: CurrentUser = None,
):
    svc = _svc(db, tenant_id, _current_user)
    config = svc.get_config(plugin_id)
    return ResponseBase.ok(data=config.model_dump())


@router.put("/{plugin_id}/config", response_model=ResponseBase)
def update_config(
    plugin_id: str,
    data: PluginConfigUpdateRequest,
    tenant_id: CurrentTenantId = None,
    db: Session = Depends(get_session),
    _current_user: CurrentUser = None,
):
    svc = _svc(db, tenant_id, _current_user)
    config = svc.update_config(plugin_id, data)
    db.commit()
    return ResponseBase.ok(data=config.model_dump())
