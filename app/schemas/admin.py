"""平台管理（超级管理员）与租户设置 Schema。"""
from typing import Optional
from datetime import datetime

from pydantic import BaseModel, Field


class TenantUsage(BaseModel):
    user_count: int = 0
    model_count: int = 0
    agent_count: int = 0
    knowledge_base_count: int = 0


class TenantSettingsOut(BaseModel):
    """当前租户设置 + 配额使用情况。"""
    id: str
    name: str
    description: Optional[str] = None
    plan: str
    max_users: int
    max_models: int
    status: bool
    created_at: Optional[datetime] = None
    usage: TenantUsage = TenantUsage()


class TenantCreate(BaseModel):
    name: str = Field(..., max_length=255)
    description: Optional[str] = Field(None, max_length=500)
    admin_email: str = Field(..., max_length=255)
    admin_password: str = Field(..., min_length=6, max_length=128)
