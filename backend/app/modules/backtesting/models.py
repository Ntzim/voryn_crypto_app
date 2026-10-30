"""Backtest runs (the spec's `backtest_runs`): request, status and the stored result."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class BacktestRun(Base):
    __tablename__ = "backtest_runs"
    __table_args__ = (
        Index("ix_backtest_runs_user_created", "user_id", "created_at"),
        CheckConstraint("status IN ('queued','running','done','failed')", name="status"),
        CheckConstraint("train_pct BETWEEN 50 AND 90", name="train_pct"),
        CheckConstraint("fee_bps >= 0 AND fee_bps <= 100", name="fee_bps"),
        CheckConstraint("slippage_bps >= 0 AND slippage_bps <= 100", name="slippage_bps"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    cryptocurrency_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cryptocurrencies.id", ondelete="CASCADE"), nullable=False
    )
    timeframe: Mapped[str] = mapped_column(String(3), nullable=False)
    strategy: Mapped[str] = mapped_column(String(32), nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    optimize: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    fee_bps: Mapped[Any] = mapped_column(Numeric(6, 2), nullable=False)
    slippage_bps: Mapped[Any] = mapped_column(Numeric(6, 2), nullable=False)
    train_pct: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(8), nullable=False, server_default="queued")
    error: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    engine_version: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
