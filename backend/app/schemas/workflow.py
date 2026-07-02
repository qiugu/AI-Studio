from datetime import datetime
from typing import Optional, List, Dict, Any

from pydantic import BaseModel, Field


# ── Workflow Node Schemas ──────────────────────────────────────────────────────

class WorkflowNodeBase(BaseModel):
    node_type: str = Field(..., description="节点类型")
    name: str = Field(..., description="节点名称")
    position_x: float = Field(default=0.0, description="X坐标")
    position_y: float = Field(default=0.0, description="Y坐标")
    config: Optional[Dict[str, Any]] = Field(default=None, description="节点配置")


class WorkflowNodeCreate(WorkflowNodeBase):
    pass


class WorkflowNodeUpdate(WorkflowNodeBase):
    node_type: Optional[str] = Field(default=None, description="节点类型")
    name: Optional[str] = Field(default=None, description="节点名称")


class WorkflowNodeResponse(WorkflowNodeBase):
    id: int
    workflow_id: int
    tenant_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ── Workflow Edge Schemas ──────────────────────────────────────────────────────

class WorkflowEdgeBase(BaseModel):
    source_node_id: int = Field(..., description="源节点ID")
    target_node_id: int = Field(..., description="目标节点ID")
    condition: Optional[Dict[str, Any]] = Field(default=None, description="条件配置")
    label: Optional[str] = Field(default=None, description="边标签")


class WorkflowEdgeCreate(WorkflowEdgeBase):
    pass


class WorkflowEdgeUpdate(WorkflowEdgeBase):
    source_node_id: Optional[int] = Field(default=None, description="源节点ID")
    target_node_id: Optional[int] = Field(default=None, description="目标节点ID")


class WorkflowEdgeResponse(WorkflowEdgeBase):
    id: int
    workflow_id: int
    tenant_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ── Workflow Schemas ────────────────────────────────────────────────────────────

class WorkflowBase(BaseModel):
    name: str = Field(..., description="工作流名称")
    description: Optional[str] = Field(default=None, description="工作流描述")


class WorkflowCreate(WorkflowBase):
    nodes: Optional[List[WorkflowNodeCreate]] = Field(default=None, description="节点列表")
    edges: Optional[List[WorkflowEdgeCreate]] = Field(default=None, description="边列表")


class WorkflowUpdate(WorkflowBase):
    name: Optional[str] = Field(default=None, description="工作流名称")
    description: Optional[str] = Field(default=None, description="工作流描述")
    status: Optional[str] = Field(default=None, description="工作流状态")
    nodes: Optional[List[WorkflowNodeCreate]] = Field(default=None, description="节点列表")
    edges: Optional[List[WorkflowEdgeCreate]] = Field(default=None, description="边列表")


class WorkflowResponse(WorkflowBase):
    id: int
    tenant_id: int
    status: str
    is_active: bool
    created_by: Optional[int]
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime]
    nodes: List[WorkflowNodeResponse] = []
    edges: List[WorkflowEdgeResponse] = []

    class Config:
        from_attributes = True


class WorkflowListResponse(BaseModel):
    items: List[WorkflowResponse]
    total: int
    page: int
    page_size: int


# ── Workflow Execution Schemas ──────────────────────────────────────────────────

class WorkflowExecutionRequest(BaseModel):
    input_data: Optional[Dict[str, Any]] = Field(default=None, description="输入参数")


class WorkflowExecutionResponse(BaseModel):
    id: int
    workflow_id: int
    tenant_id: int
    status: str
    input_data: Optional[Dict[str, Any]]
    output_data: Optional[Dict[str, Any]]
    error_message: Optional[str]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_by: Optional[int]
    created_at: datetime

    class Config:
        from_attributes = True