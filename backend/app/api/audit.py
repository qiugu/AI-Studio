"""监控审计 API：审计日志、模型调用日志、Token 统计、Dashboard。"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.core.dependencies import CurrentTenantId, CurrentUser, TenantAdmin
from app.schemas.audit import AuditLogOut, ModelCallLogOut, TokenStatsOut, DashboardOut
from app.schemas.common import ResponseBase, PaginatedData
from app.services.audit import AuditService

router = APIRouter()


@router.get("/logs", response_model=ResponseBase)
def list_audit_logs(
    _admin: TenantAdmin,
    tenant_id: CurrentTenantId,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    user_id: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    resource: Optional[str] = Query(None),
    status_code: Optional[int] = Query(None),
    start_time: Optional[datetime] = Query(None),
    end_time: Optional[datetime] = Query(None),
    db: Session = Depends(get_session),
):
    svc = AuditService(db, tenant_id)
    items, total = svc.list_audit_logs(
        page=page,
        page_size=page_size,
        user_id=user_id,
        action=action,
        resource=resource,
        status_code=status_code,
        start_time=start_time,
        end_time=end_time,
    )
    return ResponseBase.ok(
        data=PaginatedData(
            items=[AuditLogOut.model_validate(m) for m in items],
            total=total,
            page=page,
            page_size=page_size,
        ).model_dump()
    )


@router.get("/model-calls", response_model=ResponseBase)
def list_model_calls(
    _admin: TenantAdmin,
    tenant_id: CurrentTenantId,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    user_id: Optional[str] = Query(None),
    agent_id: Optional[str] = Query(None),
    model_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    start_time: Optional[datetime] = Query(None),
    end_time: Optional[datetime] = Query(None),
    db: Session = Depends(get_session),
):
    svc = AuditService(db, tenant_id)
    items, total = svc.list_model_calls(
        page=page,
        page_size=page_size,
        user_id=user_id,
        agent_id=agent_id,
        model_id=model_id,
        status=status,
        start_time=start_time,
        end_time=end_time,
    )
    return ResponseBase.ok(
        data=PaginatedData(
            items=[ModelCallLogOut.model_validate(m) for m in items],
            total=total,
            page=page,
            page_size=page_size,
        ).model_dump()
    )


@router.get("/token-stats", response_model=ResponseBase)
def token_stats(
    _current_user: CurrentUser,
    tenant_id: CurrentTenantId,
    days: int = Query(30, ge=1, le=365),
    agent_id: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    model_id: Optional[str] = Query(None),
    db: Session = Depends(get_session),
):
    svc = AuditService(db, tenant_id)
    return ResponseBase.ok(data=TokenStatsOut(**svc.token_stats(days=days, agent_id=agent_id, user_id=user_id, model_id=model_id)).model_dump())


@router.get("/dashboard", response_model=ResponseBase)
def dashboard(
    _current_user: CurrentUser,
    tenant_id: CurrentTenantId,
    db: Session = Depends(get_session),
):
    svc = AuditService(db, tenant_id)
    return ResponseBase.ok(data=DashboardOut(**svc.dashboard()).model_dump())
