from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.core.dependencies import CurrentUser, CurrentTenantId
from app.schemas.prompt import (
    PromptCreate,
    PromptUpdate,
    PromptOut,
    PromptVersionCreate,
    PromptVersionOut,
    PromptTestRequest,
    PromptTestResult,
)
from app.schemas.common import ResponseBase, PaginatedData
from app.services.prompt import PromptService

router = APIRouter()


@router.get("", response_model=ResponseBase)
def list_prompts(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    category: str | None = Query(None),
    status: str | None = Query(None),
    tenant_id: CurrentTenantId = None,
    db: Session = Depends(get_session),
    _current_user: CurrentUser = None,
):
    svc = PromptService(db, tenant_id)
    items, total = svc.list(page=page, page_size=page_size, category=category, status=status)
    return ResponseBase.ok(
        data=PaginatedData(
            items=[PromptOut.model_validate(p) for p in items],
            total=total,
            page=page,
            page_size=page_size,
        ).model_dump()
    )


@router.post("", response_model=ResponseBase)
def create_prompt(
    data: PromptCreate,
    tenant_id: CurrentTenantId = None,
    db: Session = Depends(get_session),
    current_user: CurrentUser = None,
):
    svc = PromptService(db, tenant_id)
    user_id = current_user.id if current_user else None
    prompt = svc.create(data, user_id=user_id)
    db.commit()
    return ResponseBase.ok(data=PromptOut.model_validate(prompt).model_dump())


@router.get("/{prompt_id}", response_model=ResponseBase)
def get_prompt(
    prompt_id: int,
    tenant_id: CurrentTenantId = None,
    db: Session = Depends(get_session),
    _current_user: CurrentUser = None,
):
    svc = PromptService(db, tenant_id)
    prompt = svc.get(prompt_id)
    return ResponseBase.ok(data=PromptOut.model_validate(prompt).model_dump())


@router.put("/{prompt_id}", response_model=ResponseBase)
def update_prompt(
    prompt_id: int,
    data: PromptUpdate,
    tenant_id: CurrentTenantId = None,
    db: Session = Depends(get_session),
    _current_user: CurrentUser = None,
):
    svc = PromptService(db, tenant_id)
    prompt = svc.update(prompt_id, data)
    db.commit()
    return ResponseBase.ok(data=PromptOut.model_validate(prompt).model_dump())


@router.delete("/{prompt_id}", response_model=ResponseBase)
def delete_prompt(
    prompt_id: int,
    tenant_id: CurrentTenantId = None,
    db: Session = Depends(get_session),
    _current_user: CurrentUser = None,
):
    svc = PromptService(db, tenant_id)
    svc.delete(prompt_id)
    db.commit()
    return ResponseBase.ok()


@router.get("/{prompt_id}/versions", response_model=ResponseBase)
def list_versions(
    prompt_id: int,
    tenant_id: CurrentTenantId = None,
    db: Session = Depends(get_session),
    _current_user: CurrentUser = None,
):
    svc = PromptService(db, tenant_id)
    versions = svc.list_versions(prompt_id)
    return ResponseBase.ok(data=[PromptVersionOut.model_validate(v) for v in versions])


@router.post("/{prompt_id}/versions", response_model=ResponseBase)
def create_version(
    prompt_id: int,
    data: PromptVersionCreate,
    tenant_id: CurrentTenantId = None,
    db: Session = Depends(get_session),
    current_user: CurrentUser = None,
):
    svc = PromptService(db, tenant_id)
    user_id = current_user.id if current_user else None
    version = svc.create_version(prompt_id, data, user_id=user_id)
    db.commit()
    db.refresh(version)
    return ResponseBase.ok(data=PromptVersionOut.model_validate(version).model_dump())


@router.put("/{prompt_id}/versions/{version_id}/activate", response_model=ResponseBase)
def activate_version(
    prompt_id: int,
    version_id: int,
    tenant_id: CurrentTenantId = None,
    db: Session = Depends(get_session),
    _current_user: CurrentUser = None,
):
    svc = PromptService(db, tenant_id)
    version = svc.activate_version(prompt_id, version_id)
    db.commit()
    db.refresh(version)
    return ResponseBase.ok(data=PromptVersionOut.model_validate(version).model_dump())


@router.post("/{prompt_id}/test", response_model=ResponseBase)
def test_prompt(
    prompt_id: int,
    data: PromptTestRequest,
    tenant_id: CurrentTenantId = None,
    db: Session = Depends(get_session),
    _current_user: CurrentUser = None,
):
    svc = PromptService(db, tenant_id)
    result = svc.test_run(prompt_id, data)
    db.commit()
    return ResponseBase.ok(data=result.model_dump())
