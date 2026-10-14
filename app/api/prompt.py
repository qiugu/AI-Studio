from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.core.dependencies import CurrentUser, CurrentTenantId, require_permission
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


@router.get(
    "",
    response_model=ResponseBase,
    dependencies=[Depends(require_permission("prompt", "read"))],
)
def list_prompts(
    tenant_id: CurrentTenantId,
    _current_user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    category: str | None = Query(None),
    status: str | None = Query(None),
    db: Session = Depends(get_session),
):
    svc = PromptService(db, tenant_id, actor=_current_user)
    items, total = svc.list(page=page, page_size=page_size, category=category, status=status)
    return ResponseBase.ok(
        data=PaginatedData(
            items=[PromptOut.model_validate(p) for p in items],
            total=total,
            page=page,
            page_size=page_size,
        ).model_dump()
    )


@router.post(
    "",
    response_model=ResponseBase,
    dependencies=[Depends(require_permission("prompt", "create"))],
)
def create_prompt(
    tenant_id: CurrentTenantId,
    current_user: CurrentUser,
    data: PromptCreate,
    db: Session = Depends(get_session),
):
    svc = PromptService(db, tenant_id, actor=current_user)
    user_id = current_user.id if current_user else None
    prompt = svc.create(data, user_id=user_id)
    db.commit()
    return ResponseBase.ok(data=PromptOut.model_validate(prompt).model_dump())


@router.get(
    "/{prompt_id}",
    response_model=ResponseBase,
    dependencies=[Depends(require_permission("prompt", "read"))],
)
def get_prompt(
    tenant_id: CurrentTenantId,
    _current_user: CurrentUser,
    prompt_id: str,
    db: Session = Depends(get_session),
):
    svc = PromptService(db, tenant_id, actor=_current_user)
    prompt = svc.get(prompt_id)
    return ResponseBase.ok(data=PromptOut.model_validate(prompt).model_dump())


@router.put(
    "/{prompt_id}",
    response_model=ResponseBase,
    dependencies=[Depends(require_permission("prompt", "update"))],
)
def update_prompt(
    tenant_id: CurrentTenantId,
    _current_user: CurrentUser,
    prompt_id: str,
    data: PromptUpdate,
    db: Session = Depends(get_session),
):
    svc = PromptService(db, tenant_id, actor=_current_user)
    prompt = svc.update(prompt_id, data)
    db.commit()
    return ResponseBase.ok(data=PromptOut.model_validate(prompt).model_dump())


@router.delete(
    "/{prompt_id}",
    response_model=ResponseBase,
    dependencies=[Depends(require_permission("prompt", "delete"))],
)
def delete_prompt(
    prompt_id: str,
    tenant_id: CurrentTenantId,
    _current_user: CurrentUser,
    db: Session = Depends(get_session),
):
    svc = PromptService(db, tenant_id, actor=_current_user)
    svc.delete(prompt_id)
    db.commit()
    return ResponseBase.ok()


@router.get(
    "/{prompt_id}/versions",
    response_model=ResponseBase,
    dependencies=[Depends(require_permission("prompt", "read"))],
)
def list_versions(
    prompt_id: str,
    tenant_id: CurrentTenantId,
    _current_user: CurrentUser,
    db: Session = Depends(get_session),
):
    svc = PromptService(db, tenant_id, actor=_current_user)
    versions = svc.list_versions(prompt_id)
    return ResponseBase.ok(data=[PromptVersionOut.model_validate(v) for v in versions])


@router.post(
    "/{prompt_id}/versions",
    response_model=ResponseBase,
    dependencies=[Depends(require_permission("prompt", "update"))],
)
def create_version(
    prompt_id: str,
    data: PromptVersionCreate,
    tenant_id: CurrentTenantId,
    current_user: CurrentUser,
    db: Session = Depends(get_session),
):
    svc = PromptService(db, tenant_id, actor=current_user)
    user_id = current_user.id
    version = svc.create_version(prompt_id, data, user_id=user_id)
    db.commit()
    db.refresh(version)
    return ResponseBase.ok(data=PromptVersionOut.model_validate(version).model_dump())


@router.put(
    "/{prompt_id}/versions/{version_id}/activate",
    response_model=ResponseBase,
    dependencies=[Depends(require_permission("prompt", "publish"))],
)
def activate_version(
    prompt_id: str,
    version_id: str,
    tenant_id: CurrentTenantId,
    _current_user: CurrentUser,
    db: Session = Depends(get_session),
):
    svc = PromptService(db, tenant_id, actor=_current_user)
    version = svc.activate_version(prompt_id, version_id)
    db.commit()
    db.refresh(version)
    return ResponseBase.ok(data=PromptVersionOut.model_validate(version).model_dump())


@router.post(
    "/{prompt_id}/test",
    response_model=ResponseBase,
    dependencies=[Depends(require_permission("prompt", "test"))],
)
def test_prompt(
    prompt_id: str,
    data: PromptTestRequest,
    tenant_id: CurrentTenantId,
    _current_user: CurrentUser,
    db: Session = Depends(get_session),
):
    svc = PromptService(db, tenant_id, actor=_current_user)
    result = svc.test_run(prompt_id, data)
    db.commit()
    return ResponseBase.ok(data=result.model_dump())
