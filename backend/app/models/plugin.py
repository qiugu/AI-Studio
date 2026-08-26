"""插件系统模型：plugins / plugin_configs / plugin_endpoints

插件分为两类：
- 平台公共插件：tenant_id 为 NULL 且 is_public=True，所有租户可安装使用，仅平台管理员可写
- 租户私有插件：tenant_id 为当前租户，仅该租户可见可写
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import String, Text, JSON, Boolean, DateTime, func, ForeignKey, UniqueConstraint
from sqlalchemy.orm import mapped_column, Mapped

from app.core.database import Base

import uuid


class Plugin(Base):
    """插件表"""

    __tablename__ = "plugins"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    # tenant_id 为 NULL 表示平台公共插件
    tenant_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # 插件类型：tool / provider / processor / connector
    plugin_type: Mapped[str] = mapped_column(String(50), nullable=False, default="tool")
    version: Mapped[str] = mapped_column(String(20), nullable=False, default="1.0.0")
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # 配置 Schema（JSON Schema 定义），用于前端动态渲染配置表单
    config_schema: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    icon: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    author: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    homepage_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    # OpenAPI / Swagger 规范
    api_spec: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    # 状态：active / disabled / pending_review
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    # 是否公共插件（配合 tenant_id=NULL 表示平台公共插件）
    is_public: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class PluginConfig(Base):
    """插件配置表（按租户维度）

    每个租户对同一个插件可保存多组配置（按 name 区分），例如鉴权 token、base_url 等。
    """

    __tablename__ = "plugin_configs"
    __table_args__ = (
        UniqueConstraint("plugin_id", "tenant_id", "name", name="uq_plugin_config"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    plugin_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("plugins.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    # 配置项名称，例如 "api_key" / "base_url"
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # 配置值（按 config_schema 校验，由前端/调用方保证）
    value: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class PluginEndpoint(Base):
    """插件端点表

    描述插件对外暴露的 HTTP 接口，从 OpenAPI 规范解析或直接手动维护。
    """

    __tablename__ = "plugin_endpoints"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    plugin_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("plugins.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # API 端点路径，如 /v1/search
    endpoint: Mapped[str] = mapped_column(String(500), nullable=False)
    # HTTP 方法：GET / POST / PUT / DELETE
    method: Mapped[str] = mapped_column(String(10), nullable=False, default="POST")
    # 请求头（JSON）
    headers: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    # 请求体 Schema（JSON Schema）
    request_body_schema: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    # 响应 Schema（JSON Schema）
    response_schema: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, server_default=func.now()
    )
