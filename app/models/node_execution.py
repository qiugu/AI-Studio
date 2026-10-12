from datetime import datetime
from typing import Optional
import uuid

from sqlalchemy import String, Text, DateTime, JSON, func, ForeignKey
from sqlalchemy.orm import mapped_column, Mapped, relationship

from app.core.database import Base


class NodeExecution(Base):
    """节点执行记录模型"""
    __tablename__ = "node_executions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    execution_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workflow_executions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    node_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)  # 关联 WorkflowNode.id
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)

    # 执行状态
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)  # pending | running | completed | failed | skipped
    input_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # 节点输入数据
    output_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # 节点输出数据
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # 错误信息

    # 时间戳
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    # 关系
    execution: Mapped["WorkflowExecution"] = relationship("WorkflowExecution", back_populates="node_executions")