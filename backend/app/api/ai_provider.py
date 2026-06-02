from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.core.dependencies import CurrentUser, CurrentTenantId
from app.schemas.ai_provider import (
    AIProviderCreate,
    AIProviderUpdate,
    AIProviderOut,
    ConnectivityTestRequest,
    ConnectivityTestResult,
)
from app.schemas.common import ResponseBase, PaginatedData
from app.services.ai_provider import AIProviderService

router = APIRouter()


@router.get("", response_model=ResponseBase)
def list_providers(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: bool | None = Query(None),
    tenant_id: CurrentTenantId = None,
    db: Session = Depends(get_session),
    _current_user: CurrentUser = None,
):
    svc = AIProviderService(db, tenant_id)
    items, total = svc.list(page=page, page_size=page_size, status=status)
    return ResponseBase.ok(
        data=PaginatedData(
            items=[AIProviderOut.from_orm_with_key_flag(p) for p in items],
            total=total,
            page=page,
            page_size=page_size,
        ).model_dump()
    )


@router.post("", response_model=ResponseBase)
def create_provider(
    data: AIProviderCreate,
    tenant_id: CurrentTenantId = None,
    db: Session = Depends(get_session),
    _current_user: CurrentUser = None,
):
    svc = AIProviderService(db, tenant_id)
    provider = svc.create(data)
    db.commit()
    db.refresh(provider)
    return ResponseBase.ok(data=AIProviderOut.from_orm_with_key_flag(provider).model_dump())


@router.get("/{provider_id}", response_model=ResponseBase)
def get_provider(
    provider_id: int,
    tenant_id: CurrentTenantId = None,
    db: Session = Depends(get_session),
    _current_user: CurrentUser = None,
):
    svc = AIProviderService(db, tenant_id)
    provider = svc.get(provider_id)
    return ResponseBase.ok(data=AIProviderOut.from_orm_with_key_flag(provider).model_dump())


@router.put("/{provider_id}", response_model=ResponseBase)
def update_provider(
    provider_id: int,
    data: AIProviderUpdate,
    tenant_id: CurrentTenantId = None,
    db: Session = Depends(get_session),
    _current_user: CurrentUser = None,
):
    svc = AIProviderService(db, tenant_id)
    provider = svc.update(provider_id, data)
    db.commit()
    db.refresh(provider)
    return ResponseBase.ok(data=AIProviderOut.from_orm_with_key_flag(provider).model_dump())


@router.delete("/{provider_id}", response_model=ResponseBase)
def delete_provider(
    provider_id: int,
    tenant_id: CurrentTenantId = None,
    db: Session = Depends(get_session),
    _current_user: CurrentUser = None,
):
    svc = AIProviderService(db, tenant_id)
    svc.delete(provider_id)
    db.commit()
    return ResponseBase.ok()


@router.post("/{provider_id}/test", response_model=ResponseBase)
def test_provider_connectivity(
    provider_id: int,
    data: ConnectivityTestRequest,
    tenant_id: CurrentTenantId = None,
    db: Session = Depends(get_session),
    _current_user: CurrentUser = None,
):
    svc = AIProviderService(db, tenant_id)
    result = svc.test_connectivity(provider_id, data.model_name)
    return ResponseBase.ok(data=result.model_dump())
