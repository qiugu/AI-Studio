from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, String, Text, DateTime, JSON, func
from sqlalchemy.orm import mapped_column, Mapped, relationship
from sqlalchemy import ForeignKey

from app.core.database import Base


class Message(Base):
    """消息模型"""
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)

    # 关联对话
    conversation_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )

    # 消息角色：user | assistant | system | tool
    role: Mapped[str] = mapped_column(String(20), nullable=False)

    # 消息内容
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # Token统计
    prompt_tokens: Mapped[int] = mapped_column(default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(default=0, nullable=False)
    total_tokens: Mapped[int] = mapped_column(default=0, nullable=False)

    # 工具调用信息（仅assistant角色）
    # [{"name": "tool_name", "arguments": {...}, "id": "call_123"}]
    tool_calls: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    # 工具调用结果（仅tool角色）
    tool_call_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    tool_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # 时间戳
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    # 关系
    conversation: Mapped["Conversation"] = relationship("Conversation", back_populates="messages")