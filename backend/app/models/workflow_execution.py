from datetime import datetime
from typing import Optional, List

from sqlalchemy import BigInteger, String, Text, DateTime, JSON, func, ForeignKey
from sqlalchemy.orm import mapped_column, Mapped, relationship

from app.core.database import Base


class WorkflowExecution(Base):
    """工作流执行记录模型"""
    __tablename__ = "workflow_executions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workflow_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)

    # 执行状态
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)  # pending | running | completed | failed | cancelled
    input_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # 输入参数
    output_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # 输出结果
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # 错误信息

    # 时间戳
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_by: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    # 关系
    workflow: Mapped["Workflow"] = relationship("Workflow", back_populates="executions")
    node_executions: Mapped[List["NodeExecution"]] = relationship(
        "NodeExecution", back_populates="execution", cascade="all, delete-orphan"
    )