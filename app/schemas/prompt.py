from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class PromptVersionOut(BaseModel):
    id: str
    prompt_id: str
    version_number: int
    content: str
    variables: Optional[list[str]] = None
    is_current: bool
    created_by: Optional[str]
    created_at: Optional[datetime]

    model_config = {"from_attributes": True}


class PromptOut(BaseModel):
    id: str
    tenant_id: str
    name: str
    description: Optional[str]
    category: Optional[str]
    tags: Optional[list[str]]
    status: str
    created_by: Optional[str]
    created_at: Optional[datetime]
    updated_at: Optional[datetime]
    current_version: Optional[PromptVersionOut] = None

    model_config = {"from_attributes": True}


class PromptCreate(BaseModel):
    name: str = Field(..., max_length=255)
    description: Optional[str] = None
    category: Optional[str] = Field(None, max_length=100)
    tags: Optional[list[str]] = None
    content: str = Field(..., description="Initial prompt content, may contain {{variable}} placeholders")


class PromptUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    category: Optional[str] = Field(None, max_length=100)
    tags: Optional[list[str]] = None
    status: Optional[str] = Field(None, pattern="^(draft|published|archived)$")


class PromptVersionCreate(BaseModel):
    content: str = Field(..., description="New version content")


class PromptTestRequest(BaseModel):
    version_id: Optional[str] = None
    variables: dict[str, str] = Field(default_factory=dict)
    model_id: str


class PromptTestResult(BaseModel):
    rendered_content: str
    result_content: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int
