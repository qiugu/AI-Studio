from pydantic import BaseModel
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
    last_login_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    roles: List[RoleOut] = []

    model_config = {"from_attributes": True}
