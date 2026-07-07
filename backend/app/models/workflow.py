from datetime import datetime
from typing import Optional, List
import uuid

from sqlalchemy import String, Text, DateTime, Boolean, JSON, func
from sqlalchemy.orm import mapped_column, Mapped, relationship

from app.core.database import Base


class Workflow(Base):
    """工作流模型"""
    __tablename__ = "workflows"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)

    # 基本信息
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 工作流配置
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)  # draft | published | archived
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # 时间戳
    created_by: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # 关系
    nodes: Mapped[List["WorkflowNode"]] = relationship(
        "WorkflowNode", back_populates="workflow", cascade="all, delete-orphan"
    )
    edges: Mapped[List["WorkflowEdge"]] = relationship(
        "WorkflowEdge", back_populates="workflow", cascade="all, delete-orphan"
    )
    executions: Mapped[List["WorkflowExecution"]] = relationship(
        "WorkflowExecution", back_populates="workflow", cascade="all, delete-orphan"
    )