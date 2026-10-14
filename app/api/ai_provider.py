from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.core.dependencies import CurrentUser, CurrentTenantId, require_permission
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


@router.get(
    "",
    response_model=ResponseBase,
    dependencies=[Depends(require_permission("ai_provider", "read"))],
)
def list_providers(
    _current_user: CurrentUser,
    tenant_id: CurrentTenantId,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: bool | None = Query(None),
    db: Session = Depends(get_session),
):
    svc = AIProviderService(db, tenant_id, actor=_current_user)
    items, total = svc.list(page=page, page_size=page_size, status=status)
    return ResponseBase.ok(
        data=PaginatedData(
            items=[AIProviderOut.from_orm_with_key_flag(p) for p in items],
            total=total,
            page=page,
            page_size=page_size,
        ).model_dump()
    )


@router.post(
    "",
    response_model=ResponseBase,
    dependencies=[Depends(require_permission("ai_provider", "create"))],
)
def create_provider(
    _current_user: CurrentUser,
    tenant_id: CurrentTenantId,
    data: AIProviderCreate,
    db: Session = Depends(get_session),
):
    svc = AIProviderService(db, tenant_id, actor=_current_user)
    provider = svc.create(data)
    db.commit()
    db.refresh(provider)
    return ResponseBase.ok(data=AIProviderOut.from_orm_with_key_flag(provider).model_dump())


@router.get(
    "/{provider_id}",
    response_model=ResponseBase,
    dependencies=[Depends(require_permission("ai_provider", "read"))],
)
def get_provider(
    _current_user: CurrentUser,
    tenant_id: CurrentTenantId,
    provider_id: str,
    db: Session = Depends(get_session),
):
    svc = AIProviderService(db, tenant_id, actor=_current_user)
    provider = svc.get(provider_id)
    return ResponseBase.ok(data=AIProviderOut.from_orm_with_key_flag(provider).model_dump())


@router.put(
    "/{provider_id}",
    response_model=ResponseBase,
    dependencies=[Depends(require_permission("ai_provider", "update"))],
)
def update_provider(
    _current_user: CurrentUser,
    tenant_id: CurrentTenantId,
    provider_id: str,
    data: AIProviderUpdate,
    db: Session = Depends(get_session),
):
    svc = AIProviderService(db, tenant_id, actor=_current_user)
    provider = svc.update(provider_id, data)
    db.commit()
    db.refresh(provider)
    return ResponseBase.ok(data=AIProviderOut.from_orm_with_key_flag(provider).model_dump())


@router.delete(
    "/{provider_id}",
    response_model=ResponseBase,
    dependencies=[Depends(require_permission("ai_provider", "delete"))],
)
def delete_provider(
    _current_user: CurrentUser,
    tenant_id: CurrentTenantId,
    provider_id: str,
    db: Session = Depends(get_session),
):
    svc = AIProviderService(db, tenant_id, actor=_current_user)
    svc.delete(provider_id)
    db.commit()
    return ResponseBase.ok()


@router.post(
    "/{provider_id}/test",
    response_model=ResponseBase,
    dependencies=[Depends(require_permission("ai_provider", "test"))],
)
def test_provider_connectivity(
    _current_user: CurrentUser,
    tenant_id: CurrentTenantId,
    provider_id: str,
    data: ConnectivityTestRequest,
    db: Session = Depends(get_session),
):
    svc = AIProviderService(db, tenant_id, actor=_current_user)
    result = svc.test_connectivity(provider_id, data.model_name)
    return ResponseBase.ok(data=result.model_dump())
