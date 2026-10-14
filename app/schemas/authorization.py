"""Schemas for explicit resource sharing grants."""
from datetime import datetime

from pydantic import BaseModel, Field


class ResourceGrantCreate(BaseModel):
    subject_role_id: str
    actions: list[str] = Field(min_length=1)
    expires_at: datetime | None = None


class ResourceGrantOut(BaseModel):
    id: str
    tenant_id: str
    resource_type: str
    resource_id: str
    subject_type: str
    subject_id: str
    actions: list[str]
    expires_at: datetime | None = None
    created_by: str
    revoked_at: datetime | None = None
    created_at: datetime | None = None

    model_config = {"from_attributes": True}
