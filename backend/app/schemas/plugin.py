"""插件系统 Pydantic Schemas"""
from datetime import datetime
from typing import Optional, List, Any

from pydantic import BaseModel, Field

from app.core.plugin_types import (
    DEFAULT_PLUGIN_TYPE,
    DEFAULT_SOURCE_TYPE,
    PluginSourceType,
    PluginType,
)


# ============ 插件 Schema ============


class PluginCreate(BaseModel):
    # use_enum_values=True：校验后字段以纯字符串保存，便于直接写入 ORM 列。
    model_config = {"use_enum_values": True}

    name: str = Field(..., max_length=255, description="插件名称")
    plugin_type: PluginType = Field(
        DEFAULT_PLUGIN_TYPE,
        description="能力形态（插件做什么）：tool/connector/processor",
    )
    source_type: PluginSourceType = Field(
        DEFAULT_SOURCE_TYPE,
        description="接入方式（插件怎么接进来）：http/mcp/skill",
    )
    version: str = Field("1.0.0", max_length=20)
    description: Optional[str] = None
    config_schema: Optional[dict] = Field(None, description="配置 JSON Schema")
    icon: Optional[str] = Field(None, max_length=100)
    author: Optional[str] = Field(None, max_length=255)
    homepage_url: Optional[str] = Field(None, max_length=500)
    api_spec: Optional[dict] = Field(None, description="OpenAPI/Swagger 规范")
    is_public: bool = Field(False, description="是否公共插件（仅平台管理员可创建）")
    status: str = Field("active", max_length=20, description="状态：active/disabled/pending_review")


class PluginUpdate(BaseModel):
    model_config = {"use_enum_values": True}

    name: Optional[str] = Field(None, max_length=255)
    plugin_type: Optional[PluginType] = Field(
        None, description="能力形态：tool/connector/processor"
    )
    source_type: Optional[PluginSourceType] = Field(
        None, description="接入方式：http/mcp/skill"
    )
    version: Optional[str] = Field(None, max_length=20)
    description: Optional[str] = None
    config_schema: Optional[dict] = None
    icon: Optional[str] = Field(None, max_length=100)
    author: Optional[str] = Field(None, max_length=255)
    homepage_url: Optional[str] = Field(None, max_length=500)
    api_spec: Optional[dict] = None
    is_public: Optional[bool] = None
    status: Optional[str] = Field(None, max_length=20)


class PluginEndpointOut(BaseModel):
    id: str
    plugin_id: str
    endpoint: str
    method: str
    headers: Optional[dict] = None
    request_body_schema: Optional[dict] = None
    response_schema: Optional[dict] = None
    description: Optional[str] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class PluginOut(BaseModel):
    id: str
    tenant_id: Optional[str] = None
    name: str
    # 输出层保持 str（而非枚举）：对历史数据宽容，避免个别脏值导致整体 500。
    plugin_type: str
    source_type: str
    version: str
    description: Optional[str] = None
    config_schema: Optional[dict] = None
    icon: Optional[str] = None
    author: Optional[str] = None
    homepage_url: Optional[str] = None
    api_spec: Optional[dict] = None
    status: str
    is_public: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    # 端点列表仅在详情接口填充；列表接口为空
    endpoints: List[PluginEndpointOut] = Field(default_factory=list)

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_with_endpoints(cls, obj, endpoints: Optional[List] = None) -> "PluginOut":
        data = cls.model_validate(obj)
        if endpoints is not None:
            data.endpoints = [PluginEndpointOut.model_validate(e) for e in endpoints]
        return data


# ============ 插件端点 Schema ============


class PluginEndpointCreate(BaseModel):
    endpoint: str = Field(..., max_length=500, description="API 端点路径，如 /v1/search")
    method: str = Field("POST", max_length=10, description="HTTP 方法")
    headers: Optional[dict] = None
    request_body_schema: Optional[dict] = None
    response_schema: Optional[dict] = None
    description: Optional[str] = None


class PluginEndpointUpdate(BaseModel):
    endpoint: Optional[str] = Field(None, max_length=500)
    method: Optional[str] = Field(None, max_length=10)
    headers: Optional[dict] = None
    request_body_schema: Optional[dict] = None
    response_schema: Optional[dict] = None
    description: Optional[str] = None


# ============ 插件配置 Schema ============


class PluginConfigItem(BaseModel):
    name: str = Field(..., max_length=255, description="配置项名称")
    value: Optional[Any] = Field(None, description="配置值")


class PluginConfigUpdateRequest(BaseModel):
    items: List[PluginConfigItem] = Field(..., description="配置项列表（按 name upsert）")


class PluginConfigResponse(BaseModel):
    items: List[PluginConfigItem] = Field(default_factory=list)


# ============ 测试 / 调用 Schema ============


class PluginTestRequest(BaseModel):
    # 指定要测试的端点路径；不指定则进行服务连通性探测
    endpoint: Optional[str] = Field(None, description="端点路径")
    method: Optional[str] = Field(None, max_length=10, description="HTTP 方法（覆盖端点默认方法）")
    params: Optional[dict] = Field(None, description="调用参数")


class PluginTestResult(BaseModel):
    success: bool
    status_code: Optional[int] = None
    latency_ms: Optional[int] = None
    data: Optional[Any] = None
    error: Optional[str] = None
