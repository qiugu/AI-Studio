from datetime import datetime
from typing import Optional

from sqlalchemy import String, Text, DateTime, JSON, func
from sqlalchemy.orm import mapped_column, Mapped, relationship
from sqlalchemy import ForeignKey

from app.core.database import Base

import uuid


class AgentTool(Base):
    """Agent工具关联表"""
    __tablename__ = "agent_tools"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    agent_id: Mapped[str] = mapped_column(String(36), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)

    # 工具类型：knowledge | api | function | workflow | plugin
    tool_type: Mapped[str] = mapped_column(String(50), nullable=False)

    # 工具配置（JSON格式，根据类型不同而不同）
    # knowledge: {"knowledge_base_id": 1, "top_k": 5}
    # api: {"name": "weather_api", "url": "...", "method": "GET"}
    # function: {"name": "calculate", "code": "..."}
    # workflow: {"workflow_id": 1}
    # plugin: {"plugin_id": 1, "endpoint": "search"}
    config: Mapped[dict] = mapped_column(JSON, nullable=False)

    # 工具名称和描述（用于展示）
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 是否启用
    is_enabled: Mapped[bool] = mapped_column(default=True, nullable=False)

    # 时间戳
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # 关系
    agent: Mapped["Agent"] = relationship("Agent", back_populates="tools")
