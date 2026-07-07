from datetime import datetime
from typing import Optional, List, Dict, Any

from pydantic import BaseModel, Field


# ============ Message Schemas ============


class MessageBase(BaseModel):
    """消息基础模型"""
    role: str = Field(..., description="角色：user|assistant|system|tool")
    content: str = Field(..., description="消息内容")


class MessageCreate(MessageBase):
    """创建消息"""
    prompt_tokens: int = Field(0, ge=0)
    completion_tokens: int = Field(0, ge=0)
    total_tokens: int = Field(0, ge=0)
    tool_calls: Optional[List[Dict[str, Any]]] = None
    tool_call_id: Optional[str] = None
    tool_name: Optional[str] = None


class MessageResponse(MessageBase):
    """消息响应"""
    id: str
    conversation_id: str
    tenant_id: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    tool_calls: Optional[List[Dict[str, Any]]]
    tool_call_id: Optional[str]
    tool_name: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


# ============ Conversation Schemas ============


class ConversationBase(BaseModel):
    """对话基础模型"""
    title: str = Field("新对话", max_length=255, description="对话标题")


class ConversationCreate(ConversationBase):
    """创建对话"""
    agent_id: str = Field(..., description="Agent ID")


class ConversationUpdate(BaseModel):
    """更新对话"""
    title: Optional[str] = Field(None, max_length=255)


class ConversationResponse(ConversationBase):
    """对话响应"""
    id: str
    tenant_id: str
    agent_id: str
    created_by: Optional[str]
    created_at: datetime
    updated_at: datetime
    messages: List[MessageResponse] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class ConversationListResponse(BaseModel):
    """对话列表响应"""
    items: List[ConversationResponse]
    total: int
    page: int = 1
    page_size: int = 20


# ============ Chat Schemas ============


class ChatRequest(BaseModel):
    """聊天请求"""
    message: str = Field(..., min_length=1, description="用户消息")
    conversation_id: Optional[str] = Field(None, description="对话ID，不传则创建新对话")
    stream: bool = Field(True, description="是否使用流式响应")
    messages: Optional[List[MessageBase]] = Field(
        None,
        description="对话历史消息数组（可选，如果不传则后端从数据库查询）"
    )


class ChatResponse(BaseModel):
    """聊天响应（非流式）"""
    conversation_id: str
    message: MessageResponse
