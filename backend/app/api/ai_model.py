from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.core.dependencies import CurrentUser, CurrentTenantId
from app.schemas.ai_model import (
    AIModelCreate,
    AIModelUpdate,
    AIModelOut,
    ModelTestRequest,
    ModelTestResult,
)
from app.schemas.common import ResponseBase, PaginatedData
from app.services.ai_model import AIModelService

router = APIRouter()


@router.get("", response_model=ResponseBase)
def list_models(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    model_type: str | None = Query(None),
    provider_id: int | None = Query(None),
    include_public: bool = Query(False),
    tenant_id: CurrentTenantId = None,
    db: Session = Depends(get_session),
    _current_user: CurrentUser = None,
):
    svc = AIModelService(db, tenant_id)
    items, total = svc.list(
        page=page,
        page_size=page_size,
        model_type=model_type,
        provider_id=provider_id,
        include_public=include_public,
    )
    return ResponseBase.ok(
        data=PaginatedData(
            items=[AIModelOut.model_validate(m) for m in items],
            total=total,
            page=page,
            page_size=page_size,
        ).model_dump()
    )


@router.post("", response_model=ResponseBase)
def create_model(
    data: AIModelCreate,
    tenant_id: CurrentTenantId = None,
    db: Session = Depends(get_session),
    _current_user: CurrentUser = None,
):
    svc = AIModelService(db, tenant_id)
    model = svc.create(data)
    db.commit()
    db.refresh(model)
    return ResponseBase.ok(data=AIModelOut.model_validate(model).model_dump())


@router.get("/{model_id}", response_model=ResponseBase)
def get_model(
    model_id: int,
    tenant_id: CurrentTenantId = None,
    db: Session = Depends(get_session),
    _current_user: CurrentUser = None,
):
    svc = AIModelService(db, tenant_id)
    model = svc.get(model_id)
    return ResponseBase.ok(data=AIModelOut.model_validate(model).model_dump())


@router.put("/{model_id}", response_model=ResponseBase)
def update_model(
    model_id: int,
    data: AIModelUpdate,
    tenant_id: CurrentTenantId = None,
    db: Session = Depends(get_session),
    _current_user: CurrentUser = None,
):
    svc = AIModelService(db, tenant_id)
    model = svc.update(model_id, data)
    db.commit()
    db.refresh(model)
    return ResponseBase.ok(data=AIModelOut.model_validate(model).model_dump())


@router.delete("/{model_id}", response_model=ResponseBase)
def delete_model(
    model_id: int,
    tenant_id: CurrentTenantId = None,
    db: Session = Depends(get_session),
    _current_user: CurrentUser = None,
):
    svc = AIModelService(db, tenant_id)
    svc.delete(model_id)
    db.commit()
    return ResponseBase.ok()


@router.post("/{model_id}/test", response_model=ResponseBase)
def test_model(
    model_id: int,
    data: ModelTestRequest,
    tenant_id: CurrentTenantId = None,
    db: Session = Depends(get_session),
    _current_user: CurrentUser = None,
):
    svc = AIModelService(db, tenant_id)
    result = svc.test_model(model_id, data.messages)
    return ResponseBase.ok(data=result.model_dump())
