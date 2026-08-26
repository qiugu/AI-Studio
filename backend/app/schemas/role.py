"""角色与权限管理 Schema。"""
from typing import Optional, List
from datetime import datetime

from pydantic import BaseModel, Field


class RoleCreate(BaseModel):
    name: str = Field(..., max_length=100)
    description: Optional[str] = Field(None, max_length=255)
    permission_ids: Optional[List[str]] = None


class RoleUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = Field(None, max_length=255)
    status: Optional[bool] = None


class RolePermissionAssign(BaseModel):
    permission_ids: List[str]


class RoleOut(BaseModel):
    id: str
    tenant_id: str
    name: str
    code: str
    description: Optional[str] = None
    status: bool = True
    permissions: List["PermissionOut"] = []

    model_config = {"from_attributes": True}


class PermissionOut(BaseModel):
    id: str
    resource: str
    action: str
    description: Optional[str] = None

    model_config = {"from_attributes": True}


# 解决前向引用
RoleOut.model_rebuild()
