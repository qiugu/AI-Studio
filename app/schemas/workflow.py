from datetime import datetime
from typing import Optional, List, Dict, Any, Literal
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator


NodeType = Literal[
    "start", "end", "llm", "condition", "knowledge", "code", "tool", "loop", "variable"
]
WorkflowStatus = Literal["draft", "published", "archived"]


def _normalize_node_reference(value: str) -> str:
    """接受持久化 UUID 或编辑器生成的 ``temp-*`` 节点引用。"""
    if not isinstance(value, str):
        raise ValueError("节点引用必须是字符串")
    value = value.strip()
    if value.startswith("temp-") and len(value) > 5 and not any(char.isspace() for char in value):
        return value
    try:
        return str(uuid.UUID(value))
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValueError("节点引用必须是 UUID 或 temp-* 临时 ID") from exc


# ── Workflow Node Schemas ──────────────────────────────────────────────────────

class WorkflowNodeBase(BaseModel):
    node_type: NodeType = Field(..., description="节点类型")
    name: str = Field(..., description="节点名称")
    position_x: float = Field(default=0.0, description="X坐标")
    position_y: float = Field(default=0.0, description="Y坐标")
    config: Optional[Dict[str, Any]] = Field(default=None, description="节点配置")


class WorkflowNodeCreate(WorkflowNodeBase):
    temp_id: Optional[str] = Field(default=None, description="临时节点ID（用于新建节点时的ID映射）")

    @field_validator("temp_id")
    @classmethod
    def validate_temp_id(cls, value: Optional[str]) -> Optional[str]:
        return None if value is None else _normalize_node_reference(value)


class WorkflowNodeUpdate(WorkflowNodeBase):
    node_type: Optional[NodeType] = Field(default=None, description="节点类型")
    name: Optional[str] = Field(default=None, description="节点名称")


class WorkflowNodeResponse(WorkflowNodeBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workflow_id: str
    tenant_id: str
    created_at: datetime
    updated_at: datetime

# ── Workflow Edge Schemas ──────────────────────────────────────────────────────

class WorkflowEdgeBase(BaseModel):
    source_node_id: str = Field(..., description="源节点ID")
    target_node_id: str = Field(..., description="目标节点ID")
    condition: Optional[Dict[str, Any]] = Field(default=None, description="条件配置")
    label: Optional[str] = Field(default=None, description="边标签")

    @field_validator("source_node_id", "target_node_id")
    @classmethod
    def validate_node_reference(cls, value: Optional[str]) -> Optional[str]:
        return None if value is None else _normalize_node_reference(value)


class WorkflowEdgeCreate(WorkflowEdgeBase):
    pass


class WorkflowEdgeUpdate(WorkflowEdgeBase):
    source_node_id: Optional[str] = Field(default=None, description="源节点ID")
    target_node_id: Optional[str] = Field(default=None, description="目标节点ID")


class WorkflowEdgeResponse(WorkflowEdgeBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workflow_id: str
    tenant_id: str
    created_at: datetime
    updated_at: datetime

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
    status: Optional[WorkflowStatus] = Field(default=None, description="工作流状态")
    nodes: Optional[List[WorkflowNodeCreate]] = Field(default=None, description="节点列表")
    edges: Optional[List[WorkflowEdgeCreate]] = Field(default=None, description="边列表")


class WorkflowResponse(WorkflowBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    status: WorkflowStatus
    is_active: bool
    created_by: Optional[str]
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime]
    nodes: List[WorkflowNodeResponse] = Field(default_factory=list)
    edges: List[WorkflowEdgeResponse] = Field(default_factory=list)


class WorkflowListResponse(BaseModel):
    items: List[WorkflowResponse]
    total: int
    page: int
    page_size: int


# ── Workflow Execution Schemas ──────────────────────────────────────────────────

class WorkflowExecutionRequest(BaseModel):
    input_data: Optional[Dict[str, Any]] = Field(default=None, description="输入参数")


class WorkflowExecutionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workflow_id: str
    tenant_id: str
    status: str
    input_data: Optional[Dict[str, Any]]
    output_data: Optional[Dict[str, Any]]
    error_message: Optional[str]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_by: Optional[str]
    created_at: datetime
