from datetime import datetime
from typing import Optional

from sqlalchemy import String, JSON, Boolean, DateTime, func, Text
from sqlalchemy.orm import mapped_column, Mapped

from app.core.database import Base

import uuid


class Prompt(Base):
    __tablename__ = "prompts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    tags: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    # status: draft | published | archived
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    created_by: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
