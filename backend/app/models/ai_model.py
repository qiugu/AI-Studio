from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import BigInteger, String, JSON, Boolean, DateTime, func, Integer, Numeric
from sqlalchemy.orm import mapped_column, Mapped

from app.core.database import Base


class AIModel(Base):
    __tablename__ = "ai_models"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # tenant_id 为 NULL 表示平台预置公共模型
    tenant_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, index=True)
    provider_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    model_type: Mapped[str] = mapped_column(String(50), nullable=False)
    config: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    unit_price_input: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 6), nullable=True
    )
    unit_price_output: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 6), nullable=True
    )
    max_context_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    max_output_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
