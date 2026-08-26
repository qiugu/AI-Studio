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


class TenantOut(BaseModel):
    """平台管理：租户列表/详情项。"""
    id: str
    name: str
    description: Optional[str] = None
    plan: str
    max_users: int
    max_models: int
    status: bool
    is_system_init: bool = False
    created_at: Optional[datetime] = None
    usage: Optional[TenantUsage] = None


class TenantCreate(BaseModel):
    name: str = Field(..., max_length=255)
    description: Optional[str] = Field(None, max_length=500)
    plan: str = Field(default="free", max_length=50)
    max_users: int = Field(default=10, ge=1)
    max_models: int = Field(default=5, ge=0)


class TenantUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = Field(None, max_length=500)
    plan: Optional[str] = Field(None, max_length=50)
    status: Optional[bool] = None


class TenantQuotaUpdate(BaseModel):
    max_users: Optional[int] = Field(None, ge=1)
    max_models: Optional[int] = Field(None, ge=0)
