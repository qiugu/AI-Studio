"""平台管理 API（仅超级管理员）：租户管理、配额、公共模型 CRUD。"""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.core.dependencies import PlatformAdmin
from app.schemas.admin import (
    TenantOut,
    TenantCreate,
    TenantUpdate,
    TenantQuotaUpdate,
)
from app.schemas.ai_model import AIModelCreate, AIModelUpdate, AIModelOut
from app.schemas.common import ResponseBase, PaginatedData
from app.services.admin import (
    list_tenants,
    get_tenant,
    create_tenant,
    update_tenant,
    set_quota,
    delete_tenant,
)
from app.core.exceptions import NotFoundException
from app.models.ai_model import AIModel

router = APIRouter()


# ── 租户管理 ────────────────────────────────────────────────────────────────
@router.get("/tenants", response_model=ResponseBase)
def list_tenants_api(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    search: Optional[str] = Query(None),
    db: Session = Depends(get_session),
    _admin: PlatformAdmin = None,
):
    items, total = list_tenants(db, page=page, page_size=page_size, search=search)
    return ResponseBase.ok(
        data=PaginatedData(
            items=[TenantOut(**t).model_dump() for t in items],
            total=total,
            page=page,
            page_size=page_size,
        ).model_dump()
    )


@router.post("/tenants", response_model=ResponseBase)
def create_tenant_api(
    data: TenantCreate,
    db: Session = Depends(get_session),
    _admin: PlatformAdmin = None,
):
    tenant = create_tenant(data.model_dump(), db)
    db.commit()
    db.refresh(tenant)
    return ResponseBase.ok(data=TenantOut(**get_tenant(tenant.id, db)).model_dump())


@router.get("/tenants/{tenant_id}", response_model=ResponseBase)
def get_tenant_api(
    tenant_id: str,
    db: Session = Depends(get_session),
    _admin: PlatformAdmin = None,
):
    return ResponseBase.ok(data=TenantOut(**get_tenant(tenant_id, db)).model_dump())


@router.put("/tenants/{tenant_id}", response_model=ResponseBase)
def update_tenant_api(
    tenant_id: str,
    data: TenantUpdate,
    db: Session = Depends(get_session),
    _admin: PlatformAdmin = None,
):
    result = update_tenant(tenant_id, data.model_dump(exclude_none=True), db)
    db.commit()
    return ResponseBase.ok(data=TenantOut(**result).model_dump())


@router.put("/tenants/{tenant_id}/quota", response_model=ResponseBase)
def set_quota_api(
    tenant_id: str,
    data: TenantQuotaUpdate,
    db: Session = Depends(get_session),
    _admin: PlatformAdmin = None,
):
    result = set_quota(
        tenant_id, data.max_users, data.max_models, db
    )
    db.commit()
    return ResponseBase.ok(data=TenantOut(**result).model_dump())


@router.delete("/tenants/{tenant_id}", response_model=ResponseBase)
def delete_tenant_api(
    tenant_id: str,
    db: Session = Depends(get_session),
    _admin: PlatformAdmin = None,
):
    delete_tenant(tenant_id, db)
    db.commit()
    return ResponseBase.ok()


# ── 平台公共模型（tenant_id=NULL 的 ai_models）────────────────────────────────
@router.get("/models", response_model=ResponseBase)
def list_public_models_api(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_session),
    _admin: PlatformAdmin = None,
):
    query = db.query(AIModel).filter(AIModel.tenant_id.is_(None))
    total = query.count()
    items = (
        query.order_by(AIModel.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return ResponseBase.ok(
        data=PaginatedData(
            items=[AIModelOut.model_validate(m) for m in items],
            total=total,
            page=page,
            page_size=page_size,
        ).model_dump()
    )


@router.post("/models", response_model=ResponseBase)
def create_public_model_api(
    data: AIModelCreate,
    db: Session = Depends(get_session),
    _admin: PlatformAdmin = None,
):
    model = AIModel(
        tenant_id=None,
        provider_id=data.provider_id,
        name=data.name,
        display_name=data.display_name,
        model_type=data.model_type,
        config=data.config,
        unit_price_input=data.unit_price_input,
        unit_price_output=data.unit_price_output,
        max_context_tokens=data.max_context_tokens,
        max_output_tokens=data.max_output_tokens,
        status=data.status,
    )
    db.add(model)
    db.flush()
    db.commit()
    db.refresh(model)
    return ResponseBase.ok(data=AIModelOut.model_validate(model).model_dump())


@router.put("/models/{model_id}", response_model=ResponseBase)
def update_public_model_api(
    model_id: str,
    data: AIModelUpdate,
    db: Session = Depends(get_session),
    _admin: PlatformAdmin = None,
):
    model = (
        db.query(AIModel).filter(AIModel.id == model_id, AIModel.tenant_id.is_(None)).first()
    )
    if not model:
        raise NotFoundException("AIModel", model_id)
    for key, value in data.model_dump(exclude_none=True).items():
        setattr(model, key, value)
    db.flush()
    db.commit()
    db.refresh(model)
    return ResponseBase.ok(data=AIModelOut.model_validate(model).model_dump())


@router.delete("/models/{model_id}", response_model=ResponseBase)
def delete_public_model_api(
    model_id: str,
    db: Session = Depends(get_session),
    _admin: PlatformAdmin = None,
):
    model = (
        db.query(AIModel).filter(AIModel.id == model_id, AIModel.tenant_id.is_(None)).first()
    )
    if not model:
        raise NotFoundException("AIModel", model_id)
    db.delete(model)
    db.flush()
    db.commit()
    return ResponseBase.ok()
