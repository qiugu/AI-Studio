from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse, ServerSentEvent
import json

from app.core.database import get_session
from app.core.dependencies import get_current_user, get_current_tenant, require_permission
from app.schemas.common import ResponseBase, PaginatedResponse
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

router = APIRouter(tags=["Workflow"])


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
    current_tenant=Depends(get_current_tenant),
):
    """创建工作流"""
    service = WorkflowService(db=db, tenant_id=current_tenant.id)
    workflow = service.create_workflow(data, current_user.id)
    return ResponseBase(data=WorkflowResponse.model_validate(workflow))


@router.get(
    "/{workflow_id}",
    response_model=ResponseBase[WorkflowResponse],
    dependencies=[Depends(require_permission("workflow", "read"))],
)
async def get_workflow(
    workflow_id: int,
    db: Session = Depends(get_session),
    current_tenant=Depends(get_current_tenant),
):
    """获取工作流详情"""
    service = WorkflowService(db=db, tenant_id=current_tenant.id)
    workflow = service.get_workflow(workflow_id)
    return ResponseBase(data=WorkflowResponse.model_validate(workflow))


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
):
    """列出工作流"""
    service = WorkflowService(db=db, tenant_id=current_tenant.id)
    workflows, total = service.list_workflows(page=page, page_size=page_size, status=status)
    items = [WorkflowResponse.model_validate(w) for w in workflows]
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
    workflow_id: int,
    data: WorkflowUpdate,
    db: Session = Depends(get_session),
    current_tenant=Depends(get_current_tenant),
):
    """更新工作流"""
    service = WorkflowService(db=db, tenant_id=current_tenant.id)
    workflow = service.update_workflow(workflow_id, data)
    return ResponseBase(data=WorkflowResponse.model_validate(workflow))


@router.delete(
    "/{workflow_id}",
    response_model=ResponseBase,
    dependencies=[Depends(require_permission("workflow", "delete"))],
)
async def delete_workflow(
    workflow_id: int,
    db: Session = Depends(get_session),
    current_tenant=Depends(get_current_tenant),
):
    """删除工作流"""
    service = WorkflowService(db=db, tenant_id=current_tenant.id)
    service.delete_workflow(workflow_id)
    return ResponseBase(message="工作流已删除")


# ── Workflow状态管理 ───────────────────────────────────────────────────────────

@router.post(
    "/{workflow_id}/publish",
    response_model=ResponseBase[WorkflowResponse],
    dependencies=[Depends(require_permission("workflow", "update"))],
)
async def publish_workflow(
    workflow_id: int,
    db: Session = Depends(get_session),
    current_tenant=Depends(get_current_tenant),
):
    """发布工作流"""
    service = WorkflowService(db=db, tenant_id=current_tenant.id)
    workflow = service.publish_workflow(workflow_id)
    return ResponseBase(data=WorkflowResponse.model_validate(workflow))


@router.post(
    "/{workflow_id}/archive",
    response_model=ResponseBase[WorkflowResponse],
    dependencies=[Depends(require_permission("workflow", "update"))],
)
async def archive_workflow(
    workflow_id: int,
    db: Session = Depends(get_session),
    current_tenant=Depends(get_current_tenant),
):
    """归档工作流"""
    service = WorkflowService(db=db, tenant_id=current_tenant.id)
    workflow = service.archive_workflow(workflow_id)
    return ResponseBase(data=WorkflowResponse.model_validate(workflow))


# ── Workflow执行 ───────────────────────────────────────────────────────────────

@router.post(
    "/{workflow_id}/execute",
    response_model=ResponseBase[WorkflowExecutionResponse],
    dependencies=[Depends(require_permission("workflow", "execute"))],
)
async def execute_workflow(
    workflow_id: int,
    data: WorkflowExecutionRequest,
    db: Session = Depends(get_session),
    current_user=Depends(get_current_user),
    current_tenant=Depends(get_current_tenant),
):
    """执行工作流（阻塞式）"""
    engine = WorkflowEngine(db=db, tenant_id=current_tenant.id)
    result = await engine.execute_workflow(
        workflow_id=workflow_id,
        input_data=data.input_data,
        user_id=current_user.id,
    )

    # 获取执行记录
    from app.models.workflow_execution import WorkflowExecution
    execution = db.query(WorkflowExecution).filter(
        WorkflowExecution.id == result["execution_id"],
        WorkflowExecution.tenant_id == current_tenant.id,
    ).first()

    return ResponseBase(data=WorkflowExecutionResponse.model_validate(execution))


@router.post(
    "/{workflow_id}/execute/stream",
    dependencies=[Depends(require_permission("workflow", "execute"))],
)
async def execute_workflow_stream(
    workflow_id: int,
    data: WorkflowExecutionRequest,
    db: Session = Depends(get_session),
    current_user=Depends(get_current_user),
    current_tenant=Depends(get_current_tenant),
):
    """执行工作流（SSE流式）"""
    engine = WorkflowEngine(db=db, tenant_id=current_tenant.id)

    async def event_generator():
        async for event in engine.execute_workflow_stream(
            workflow_id=workflow_id,
            input_data=data.input_data,
            user_id=current_user.id,
        ):
            yield ServerSentEvent(
                event=event["type"],
                data=json.dumps(event, ensure_ascii=False),
            )

    return EventSourceResponse(event_generator(), media_type="text/event-stream")


@router.get(
    "/{workflow_id}/validate",
    response_model=ResponseBase,
    dependencies=[Depends(require_permission("workflow", "read"))],
)
async def validate_workflow(
    workflow_id: int,
    db: Session = Depends(get_session),
    current_tenant=Depends(get_current_tenant),
):
    """验证工作流DAG结构"""
    service = WorkflowService(db=db, tenant_id=current_tenant.id)
    result = service.validate_workflow_dag(workflow_id)
    return ResponseBase(data=result)