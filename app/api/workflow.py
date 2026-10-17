from typing import Optional
import uuid
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.core.authorization import AuthorizationService
from app.core.dependencies import get_current_user, get_current_tenant, require_permission, require_tenant_user
from app.services.resource_authorization import (
    ResourceAuthorizationService,
    ResourceGrantService,
)
from app.schemas.common import ResponseBase, PaginatedResponse
from app.schemas.authorization import ResourceGrantCreate, ResourceGrantOut
from app.schemas.workflow import (
    WorkflowCreate,
    WorkflowUpdate,
    WorkflowResponse,
    WorkflowListResponse,
    WorkflowExecutionRequest,
    WorkflowExecutionResponse,
)
from app.services.workflow import WorkflowService
from app.services.workflow_engine import WorkflowEngine
from app.utils.sse import create_sse_response, json_sse_event

router = APIRouter(tags=["Workflow"], dependencies=[Depends(require_tenant_user)])


def _authorize_workflow(
    db: Session,
    current_user,
    workflow,
    action: str,
) -> None:
    ResourceAuthorizationService(db).require(
        current_user,
        current_user.tenant_id,
        "workflow",
        action,
        workflow,
    )


def _workflow_response(db: Session, current_user, workflow) -> WorkflowResponse:
    payload = WorkflowResponse.model_validate(workflow)
    payload.allowed_actions = ResourceAuthorizationService(db).allowed_actions(
        current_user,
        current_user.tenant_id,
        "workflow",
        workflow,
    )
    return payload


# ── Workflow CRUD ───────────────────────────────────────────────────────────────

@router.post(
    "",
    response_model=ResponseBase[WorkflowResponse],
    dependencies=[Depends(require_permission("workflow", "create"))],
)
async def create_workflow(
    data: WorkflowCreate,
    db: Session = Depends(get_session),
    current_user=Depends(get_current_user),
    tenant_id=Depends(get_current_tenant),
):
    """创建工作流"""
    service = WorkflowService(db=db, tenant_id=tenant_id, actor=current_user)
    workflow = service.create_workflow(data, current_user.id)
    return ResponseBase(data=_workflow_response(db, current_user, workflow))


@router.get(
    "/{workflow_id}",
    response_model=ResponseBase[WorkflowResponse],
    dependencies=[Depends(require_permission("workflow", "read"))],
)
async def get_workflow(
    workflow_id: uuid.UUID,
    db: Session = Depends(get_session),
    tenant_id=Depends(get_current_tenant),
    current_user=Depends(get_current_user),
):
    """获取工作流详情"""
    service = WorkflowService(db=db, tenant_id=tenant_id, actor=current_user)
    workflow = service.get_workflow(workflow_id)
    _authorize_workflow(db, current_user, workflow, "read")
    return ResponseBase(data=_workflow_response(db, current_user, workflow))


@router.get(
    "/{workflow_id}/export",
    response_model=ResponseBase[WorkflowResponse],
    dependencies=[Depends(require_permission("workflow", "export"))],
)
async def export_workflow(
    workflow_id: uuid.UUID,
    db: Session = Depends(get_session),
    tenant_id=Depends(get_current_tenant),
    current_user=Depends(get_current_user),
):
    """导出工作流定义（仍按当前租户和 workflow.export 授权）。"""
    service = WorkflowService(db=db, tenant_id=tenant_id, actor=current_user)
    workflow = service.get_workflow(workflow_id, authorize=False)
    _authorize_workflow(db, current_user, workflow, "export")
    return ResponseBase(data=_workflow_response(db, current_user, workflow))


@router.get(
    "",
    response_model=ResponseBase[WorkflowListResponse],
    dependencies=[Depends(require_permission("workflow", "read"))],
)
async def list_workflows(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None),
    db: Session = Depends(get_session),
    current_tenant=Depends(get_current_tenant),
    current_user=Depends(get_current_user),
):
    """列出工作流"""
    service = WorkflowService(db=db, tenant_id=current_tenant, actor=current_user)
    can_manage_drafts = (await AuthorizationService(db).check_permission_async(
        current_user,
        current_tenant,
        "workflow",
        "update",
    )).allowed
    if not can_manage_drafts:
        status = "published"
    workflows, total = service.list_workflows(page=page, page_size=page_size, status=status)
    items = [_workflow_response(db, current_user, w) for w in workflows]
    return ResponseBase(
        data=WorkflowListResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
        )
    )


@router.put(
    "/{workflow_id}",
    response_model=ResponseBase[WorkflowResponse],
    dependencies=[Depends(require_permission("workflow", "update"))],
)
async def update_workflow(
    workflow_id: uuid.UUID,
    data: WorkflowUpdate,
    db: Session = Depends(get_session),
    current_tenant=Depends(get_current_tenant),
    current_user=Depends(get_current_user),
):
    """更新工作流"""
    service = WorkflowService(db=db, tenant_id=current_tenant, actor=current_user)
    _authorize_workflow(db, current_user, service.get_workflow(workflow_id), "update")
    workflow = service.update_workflow(workflow_id, data)
    return ResponseBase(data=_workflow_response(db, current_user, workflow))


@router.delete(
    "/{workflow_id}",
    response_model=ResponseBase,
    dependencies=[Depends(require_permission("workflow", "delete"))],
)
async def delete_workflow(
    workflow_id: uuid.UUID,
    db: Session = Depends(get_session),
    current_tenant=Depends(get_current_tenant),
    current_user=Depends(get_current_user),
):
    """删除工作流"""
    service = WorkflowService(db=db, tenant_id=current_tenant, actor=current_user)
    _authorize_workflow(db, current_user, service.get_workflow(workflow_id), "delete")
    service.delete_workflow(workflow_id)
    return ResponseBase(message="工作流已删除")


@router.post("/{workflow_id}/grants", response_model=ResponseBase)
async def create_workflow_grant(
    workflow_id: uuid.UUID,
    data: ResourceGrantCreate,
    db: Session = Depends(get_session),
    current_user=Depends(get_current_user),
    current_tenant=Depends(get_current_tenant),
):
    service = WorkflowService(db=db, tenant_id=current_tenant, actor=current_user)
    workflow = service.get_workflow(workflow_id)
    grant = ResourceGrantService(db).create_grant(
        current_user,
        current_tenant,
        "workflow",
        workflow,
        subject_role_id=data.subject_role_id,
        actions=data.actions,
        expires_at=data.expires_at,
    )
    db.commit()
    db.refresh(grant)
    return ResponseBase.ok(data=ResourceGrantOut.model_validate(grant).model_dump())


@router.delete("/{workflow_id}/grants/{grant_id}", response_model=ResponseBase)
async def revoke_workflow_grant(
    workflow_id: uuid.UUID,
    grant_id: str,
    db: Session = Depends(get_session),
    current_user=Depends(get_current_user),
    current_tenant=Depends(get_current_tenant),
):
    service = WorkflowService(db=db, tenant_id=current_tenant, actor=current_user)
    service.get_workflow(workflow_id)
    grant = ResourceGrantService(db).revoke_grant(
        current_user,
        current_tenant,
        grant_id,
        resource="workflow",
        resource_id=str(workflow_id),
    )
    db.commit()
    db.refresh(grant)
    return ResponseBase.ok(data=ResourceGrantOut.model_validate(grant).model_dump())


# ── Workflow状态管理 ───────────────────────────────────────────────────────────

@router.post(
    "/{workflow_id}/publish",
    response_model=ResponseBase[WorkflowResponse],
    dependencies=[Depends(require_permission("workflow", "publish"))],
)
async def publish_workflow(
    workflow_id: uuid.UUID,
    db: Session = Depends(get_session),
    current_tenant=Depends(get_current_tenant),
    current_user=Depends(get_current_user),
):
    """发布工作流"""
    service = WorkflowService(db=db, tenant_id=current_tenant, actor=current_user)
    _authorize_workflow(db, current_user, service.get_workflow(workflow_id), "publish")
    workflow = service.publish_workflow(workflow_id)
    return ResponseBase(data=_workflow_response(db, current_user, workflow))


@router.post(
    "/{workflow_id}/archive",
    response_model=ResponseBase[WorkflowResponse],
    dependencies=[Depends(require_permission("workflow", "update"))],
)
async def archive_workflow(
    workflow_id: uuid.UUID,
    db: Session = Depends(get_session),
    current_tenant=Depends(get_current_tenant),
    current_user=Depends(get_current_user),
):
    """归档工作流"""
    service = WorkflowService(db=db, tenant_id=current_tenant, actor=current_user)
    _authorize_workflow(db, current_user, service.get_workflow(workflow_id), "update")
    workflow = service.archive_workflow(workflow_id)
    return ResponseBase(data=_workflow_response(db, current_user, workflow))


# ── Workflow执行 ───────────────────────────────────────────────────────────────

@router.post(
    "/{workflow_id}/execute",
    response_model=ResponseBase[WorkflowExecutionResponse],
    dependencies=[Depends(require_permission("workflow", "execute"))],
)
async def execute_workflow(
    workflow_id: uuid.UUID,
    data: WorkflowExecutionRequest,
    db: Session = Depends(get_session),
    current_user=Depends(get_current_user),
    current_tenant=Depends(get_current_tenant),
):
    """执行工作流（阻塞式）"""
    workflow = WorkflowService(db=db, tenant_id=current_tenant).get_workflow(workflow_id)
    _authorize_workflow(db, current_user, workflow, "execute")
    engine = WorkflowEngine(db=db, tenant_id=current_tenant, actor=current_user)
    result = await engine.execute_workflow(
        workflow_id=workflow_id,
        input_data=data.input_data,
        user_id=current_user.id,
    )

    from app.models.workflow_execution import WorkflowExecution
    execution = db.query(WorkflowExecution).filter(
        WorkflowExecution.id == result["execution_id"],
        WorkflowExecution.tenant_id == current_tenant,
    ).first()

    return ResponseBase(data=WorkflowExecutionResponse.model_validate(execution))


@router.post(
    "/{workflow_id}/execute/stream",
    dependencies=[Depends(require_permission("workflow", "execute"))],
)
async def execute_workflow_stream(
    workflow_id: uuid.UUID,
    data: WorkflowExecutionRequest,
    db: Session = Depends(get_session),
    current_user=Depends(get_current_user),
    current_tenant=Depends(get_current_tenant),
):
    """执行工作流（SSE流式）"""
    workflow = WorkflowService(db=db, tenant_id=current_tenant).get_workflow(workflow_id)
    _authorize_workflow(db, current_user, workflow, "execute")
    engine = WorkflowEngine(db=db, tenant_id=current_tenant, actor=current_user)

    async def event_generator():
        async for event in engine.execute_workflow_stream(
            workflow_id=workflow_id,
            input_data=data.input_data,
            user_id=current_user.id,
        ):
            yield json_sse_event(event["type"], event)

    return create_sse_response(event_generator())


@router.get(
    "/{workflow_id}/validate",
    response_model=ResponseBase,
    dependencies=[Depends(require_permission("workflow", "read"))],
)
async def validate_workflow(
    workflow_id: uuid.UUID,
    db: Session = Depends(get_session),
    current_tenant=Depends(get_current_tenant),
    current_user=Depends(get_current_user),
):
    """验证工作流DAG结构"""
    service = WorkflowService(db=db, tenant_id=current_tenant, actor=current_user)
    _authorize_workflow(db, current_user, service.get_workflow(workflow_id), "read")
    result = service.validate_workflow_dag(workflow_id)
    return ResponseBase(data=result)
