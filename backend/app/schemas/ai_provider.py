from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class AIProviderCreate(BaseModel):
    name: str = Field(..., max_length=255)
    provider_type: str = Field(..., max_length=50)
    api_base_url: Optional[str] = Field(None, max_length=500)
    # api_key 是明文，服务层加密存储；响应中不返回
    api_key: Optional[str] = None
    config: Optional[dict] = None
    status: bool = True


class AIProviderUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    provider_type: Optional[str] = Field(None, max_length=50)
    api_base_url: Optional[str] = Field(None, max_length=500)
    api_key: Optional[str] = None
    config: Optional[dict] = None
    status: Optional[bool] = None


class AIProviderOut(BaseModel):
    id: int
    tenant_id: int
    name: str
    provider_type: str
    api_base_url: Optional[str]
    # 不返回解密后的 api_key，仅告知是否已配置
    has_api_key: bool
    config: Optional[dict]
    status: bool
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_with_key_flag(cls, obj) -> "AIProviderOut":
        return cls(
            id=obj.id,
            tenant_id=obj.tenant_id,
            name=obj.name,
            provider_type=obj.provider_type,
            api_base_url=obj.api_base_url,
            has_api_key=bool(obj.api_key_encrypted),
            config=obj.config,
            status=obj.status,
            created_at=obj.created_at,
            updated_at=obj.updated_at,
        )


class ConnectivityTestRequest(BaseModel):
    model_name: str = Field(..., description="用于测试的模型名称，如 gpt-4o-mini")


class ConnectivityTestResult(BaseModel):
    success: bool
    latency_ms: Optional[int] = None
    error: Optional[str] = None
