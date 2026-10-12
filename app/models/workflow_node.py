from datetime import datetime
from typing import Optional, List
import uuid

from sqlalchemy import String, Text, DateTime, Float, JSON, func, ForeignKey
from sqlalchemy.orm import mapped_column, Mapped, relationship

from app.core.database import Base


class WorkflowNode(Base):
    """工作流节点模型"""
    __tablename__ = "workflow_nodes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    workflow_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)

    # 节点信息
    node_type: Mapped[str] = mapped_column(String(50), nullable=False)  # start | end | llm | condition | knowledge | code | tool | loop | variable
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # 位置信息（用于前端React Flow）
    position_x: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    position_y: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    # 节点配置（JSON格式，不同节点类型有不同的配置）
    config: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # 时间戳
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # 关系
    workflow: Mapped["Workflow"] = relationship("Workflow", back_populates="nodes")
    source_edges: Mapped[List["WorkflowEdge"]] = relationship(
        "WorkflowEdge", foreign_keys="WorkflowEdge.source_node_id", back_populates="source_node"
    )
    target_edges: Mapped[List["WorkflowEdge"]] = relationship(
        "WorkflowEdge", foreign_keys="WorkflowEdge.target_node_id", back_populates="target_node"
    )