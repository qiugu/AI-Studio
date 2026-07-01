from datetime import datetime
from typing import Optional, List, Dict, Any

from pydantic import BaseModel, Field


# ============ Agent Tool Schemas ============


class AgentToolBase(BaseModel):
    """Agent工具基础模型"""
    tool_type: str = Field(..., description="工具类型：knowledge|api|function|workflow|plugin")
    config: Dict[str, Any] = Field(..., description="工具配置")
    name: str = Field(..., description="工具名称")
    description: Optional[str] = Field(None, description="工具描述")
    is_enabled: bool = Field(True, description="是否启用")


class AgentToolCreate(AgentToolBase):
    """创建Agent工具"""
    pass


class AgentToolUpdate(BaseModel):
    """更新Agent工具"""
    tool_type: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    name: Optional[str] = None
    description: Optional[str] = None
    is_enabled: Optional[bool] = None


class AgentToolResponse(AgentToolBase):
    """Agent工具响应"""
    id: int
    agent_id: int
    tenant_id: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ============ Agent Schemas ============


class AgentBase(BaseModel):
    """Agent基础模型"""
    name: str = Field(..., min_length=1, max_length=255, description="Agent名称")
    description: Optional[str] = Field(None, description="Agent描述")
    avatar: Optional[str] = Field(None, description="头像URL")
    system_prompt: Optional[str] = Field(None, description="系统提示词")
    model_id: int = Field(..., description="关联的AI模型ID")
    temperature: float = Field(0.7, ge=0.0, le=2.0, description="温度参数")
    max_tokens: int = Field(2000, ge=1, le=32000, description="最大Token数")


class AgentCreate(AgentBase):
    """创建Agent"""
    tools: Optional[List[AgentToolCreate]] = Field(default_factory=list, description="工具列表")
    status: str = Field("draft", description="状态：draft|published")


class AgentUpdate(BaseModel):
    """更新Agent"""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    avatar: Optional[str] = None
    system_prompt: Optional[str] = None
    model_id: Optional[int] = None
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(None, ge=1, le=32000)
    status: Optional[str] = None
    tools: Optional[List[AgentToolCreate]] = None


class AgentResponse(AgentBase):
    """Agent响应"""
    id: int
    tenant_id: int
    status: str
    created_by: Optional[int]
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime]
    tools: List[AgentToolResponse] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class AgentListResponse(BaseModel):
    """Agent列表响应"""
    items: List[AgentResponse]
    total: int
    page: int = 1
    page_size: int = 20