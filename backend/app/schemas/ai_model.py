from datetime import datetime
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel, Field


class AIModelCreate(BaseModel):
    provider_id: int
    name: str = Field(..., max_length=255, description="模型标识，如 gpt-4o")
    display_name: str = Field(..., max_length=255)
    model_type: str = Field(..., max_length=50, description="chat/embedding/image/audio/rerank")
    config: Optional[dict] = None
    unit_price_input: Optional[Decimal] = None
    unit_price_output: Optional[Decimal] = None
    max_context_tokens: Optional[int] = None
    max_output_tokens: Optional[int] = None
    status: bool = True


class AIModelUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    display_name: Optional[str] = Field(None, max_length=255)
    model_type: Optional[str] = Field(None, max_length=50)
    config: Optional[dict] = None
    unit_price_input: Optional[Decimal] = None
    unit_price_output: Optional[Decimal] = None
    max_context_tokens: Optional[int] = None
    max_output_tokens: Optional[int] = None
    status: Optional[bool] = None


class AIModelOut(BaseModel):
    id: int
    tenant_id: Optional[int]
    provider_id: int
    name: str
    display_name: str
    model_type: str
    config: Optional[dict]
    unit_price_input: Optional[Decimal]
    unit_price_output: Optional[Decimal]
    max_context_tokens: Optional[int]
    max_output_tokens: Optional[int]
    status: bool
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    model_config = {"from_attributes": True}


class ModelTestRequest(BaseModel):
    messages: list[dict] = Field(
        ...,
        description="消息列表，格式: [{role: 'user', content: '...'}]"
    )


class ModelTestResult(BaseModel):
    content: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int
