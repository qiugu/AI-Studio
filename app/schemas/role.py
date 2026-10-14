"""角色与权限管理 Schema。"""
from typing import Optional, List
from datetime import datetime

from pydantic import BaseModel, Field


class RoleCreate(BaseModel):
    name: str = Field(..., max_length=100)
    description: Optional[str] = Field(None, max_length=255)
    permission_ids: Optional[List[str]] = None
    current_password: Optional[str] = Field(None, min_length=1, max_length=128)


class RoleUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = Field(None, max_length=255)
    status: Optional[bool] = None
    current_password: Optional[str] = Field(None, min_length=1, max_length=128)


class RolePermissionAssign(BaseModel):
    permission_ids: List[str]
    current_password: Optional[str] = Field(None, min_length=1, max_length=128)


class RoleOut(BaseModel):
    id: str
    tenant_id: str
    name: str
    code: str
    description: Optional[str] = None
    status: bool = True
    is_admin: bool = False
    permissions: List["PermissionOut"] = []

    model_config = {"from_attributes": True}


class PermissionOut(BaseModel):
    id: str
    key: Optional[str] = None
    resource: str
    action: str
    description: Optional[str] = None
    scope: str = "tenant"
    sensitivity: str = "normal"
    is_delegable: bool = True

    model_config = {"from_attributes": True}


# 解决前向引用
RoleOut.model_rebuild()
