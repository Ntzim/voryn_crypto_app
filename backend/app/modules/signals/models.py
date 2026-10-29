"""Signals storage.

- `signal_strategies`: versioned scoring configuration (weights, thresholds). A change of
  weights is a new version, so historical signals stay interpretable.
- `analysis_signals`: one row per (asset, timeframe, strategy version, closed candle) —
  regenerating the same candle is a no-op, which makes the history auditable.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.modules.market_data.models import Price


class SignalStrategy(Base):
    __tablename__ = "signal_strategies"
    __table_args__ = (UniqueConstraint("key", "version"),)

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    key: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    #: {"trend": "0.25", ...} — validated on load; must cover every component.
    weights: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    #: {"buy": "65", "sell": "35"}
    thresholds: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AnalysisSignal(Base):
    __tablename__ = "analysis_signals"
    __table_args__ = (
        UniqueConstraint("cryptocurrency_id", "timeframe", "strategy_id", "candle_time"),
        Index("ix_analysis_signals_latest", "timeframe", "strategy_id", "candle_time"),
        Index("ix_analysis_signals_asset", "cryptocurrency_id", "timeframe", "candle_time"),
        CheckConstraint("score >= 0 AND score <= 100", name="score_range"),
        CheckConstraint(
            "classification IN ('buy_potential', 'neutral', 'attention', 'sell_potential')",
            name="classification_valid",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    cryptocurrency_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cryptocurrencies.id", ondelete="CASCADE"), nullable=False
    )
    timeframe: Mapped[str] = mapped_column(String(3), nullable=False)
    strategy_id: Mapped[int] = mapped_column(ForeignKey("signal_strategies.id"), nullable=False)
    #: open time of the closed candle the signal was computed on
    candle_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    reference_price: Mapped[Decimal] = mapped_column(Price, nullable=False)
    score: Mapped[Decimal] = mapped_column(Numeric(5, 1), nullable=False)
    classification: Mapped[str] = mapped_column(String(16), nullable=False)
    components: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    indicators: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    trend: Mapped[str] = mapped_column(String(16), nullable=False)
    justification: Mapped[str] = mapped_column(Text, nullable=False)
    risks: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    invalidation: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    data_source: Mapped[str] = mapped_column(String(64), nullable=False)
    data_fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    data_is_stale: Mapped[bool] = mapped_column(Boolean, nullable=False)
    methodology_version: Mapped[str] = mapped_column(String(16), nullable=False)
