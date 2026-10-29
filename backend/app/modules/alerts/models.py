"""Alerts and notifications.

Alerts are *edge-triggered*: they fire when their condition becomes true (a crossing), not
on every evaluation while it stays true. `last_state` stores the previous evaluation, the
cooldown bounds how often one alert can notify, and `notifications.dedupe_key` makes a
duplicate delivery impossible even if the evaluator runs twice concurrently.
"""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin


class AlertType(enum.StrEnum):
    PRICE_ABOVE = "price_above"
    PRICE_BELOW = "price_below"
    RSI_ABOVE = "rsi_above"
    RSI_BELOW = "rsi_below"
    MA_CROSS = "ma_cross"
    VOLUME_SPIKE = "volume_spike"
    TREND_CHANGE = "trend_change"
    SIGNAL_CHANGE = "signal_change"
    CONCENTRATION = "concentration"


#: Types evaluated on candles of a timeframe.
INDICATOR_TYPES = frozenset(
    {
        AlertType.RSI_ABOVE,
        AlertType.RSI_BELOW,
        AlertType.MA_CROSS,
        AlertType.VOLUME_SPIKE,
        AlertType.TREND_CHANGE,
        AlertType.SIGNAL_CHANGE,
    }
)


class Alert(TimestampMixin, Base):
    __tablename__ = "alerts"
    __table_args__ = (
        Index("ix_alerts_user_id", "user_id"),
        Index("ix_alerts_active", "is_active"),
        CheckConstraint("cooldown_minutes BETWEEN 15 AND 10080", name="cooldown_range"),
        CheckConstraint(
            "timeframe IS NULL OR timeframe IN ('15m', '1h', '4h', '1d', '1w')",
            name="timeframe_supported",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[AlertType] = mapped_column(
        Enum(AlertType, name="alert_type", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    #: NULL only for portfolio-wide concentration alerts.
    cryptocurrency_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("cryptocurrencies.id", ondelete="CASCADE")
    )
    timeframe: Mapped[str | None] = mapped_column(String(3))
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    notify_email: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    cooldown_minutes: Mapped[int] = mapped_column(Integer, nullable=False, server_default="360")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    last_state: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    last_evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    trigger_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("user_id", "dedupe_key"),
        Index("ix_notifications_user_created", "user_id", "created_at"),
        Index("ix_notifications_user_unread", "user_id", "read_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    alert_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("alerts.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(16), nullable=False, server_default="alert")
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    #: e.g. {"asset_slug": "bitcoin", "value": "100250.1"} — for deep links in the UI
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    dedupe_key: Mapped[str] = mapped_column(String(160), nullable=False)
    channels: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default="[]")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
