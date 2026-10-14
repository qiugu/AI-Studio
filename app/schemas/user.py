from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class PermissionOut(BaseModel):
    id: str
    resource: str
    action: str
    description: Optional[str] = None

    model_config = {"from_attributes": True}


class RoleOut(BaseModel):
    id: str
    name: str
    code: str
    description: Optional[str] = None
    status: bool = True
    is_admin: bool = False
    permissions: List[PermissionOut] = []

    model_config = {"from_attributes": True}


class UserOut(BaseModel):
    id: str
    tenant_id: str
    email: str
    nickname: Optional[str] = None
    avatar: Optional[str] = None
    status: bool = True
    is_platform_admin: bool = False
    email_verified: bool = False
    is_tenant_owner: bool = False
    last_login_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    roles: List[RoleOut] = []
    capabilities: List[str] = []

    model_config = {"from_attributes": True}


class UserCreate(BaseModel):
    email: str
    password: str
    nickname: Optional[str] = None
    role_ids: Optional[List[str]] = None  # 可指定初始角色，默认 tenant_member


class UserUpdate(BaseModel):
    nickname: Optional[str] = None
    # 仅为存量客户端提供明确的服务端拒绝路径；管理员密码必须走独立重置接口。
    password: Optional[str] = None
    status: Optional[bool] = None
    role_ids: Optional[List[str]] = None  # 全量覆盖用户角色
    current_password: Optional[str] = Field(None, min_length=1, max_length=128)


class UserRoleAssign(BaseModel):
    role_ids: List[str]
    current_password: Optional[str] = Field(None, min_length=1, max_length=128)


class PasswordResetRequest(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=128)


class PasswordResetComplete(BaseModel):
    token: str = Field(..., min_length=20, max_length=256)
    password: str = Field(..., min_length=12, max_length=128)
