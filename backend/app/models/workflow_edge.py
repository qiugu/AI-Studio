from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, String, Text, DateTime, JSON, func, ForeignKey
from sqlalchemy.orm import mapped_column, Mapped, relationship

from app.core.database import Base


class WorkflowEdge(Base):
    """工作流边（连线）模型"""
    __tablename__ = "workflow_edges"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workflow_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)

    # 边信息
    source_node_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("workflow_nodes.id", ondelete="CASCADE"), nullable=False
    )
    target_node_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("workflow_nodes.id", ondelete="CASCADE"), nullable=False
    )

    # 条件配置（用于条件分支）
    condition: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # {"expression": "{{output.value > 10}}", "label": "大于10"}
    label: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)  # 边的标签（显示在连线上）

    # 时间戳
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # 关系
    workflow: Mapped["Workflow"] = relationship("Workflow", back_populates="edges")
    source_node: Mapped["WorkflowNode"] = relationship(
        "WorkflowNode", foreign_keys=[source_node_id], back_populates="source_edges"
    )
    target_node: Mapped["WorkflowNode"] = relationship(
        "WorkflowNode", foreign_keys=[target_node_id], back_populates="target_edges"
    )