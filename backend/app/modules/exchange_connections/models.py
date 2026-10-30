"""Read-only exchange connections and the records synced from them.

Credentials are encrypted at rest (Fernet, ENCRYPTION_KEYS) and never leave the backend.
Synced records are stored once per connection (deduplicated by the exchange's own id) and
then imported into the portfolio as transactions; anything that cannot be imported safely
stays as a record "needs_review" with the reason.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin


class ExchangeConnection(TimestampMixin, Base):
    __tablename__ = "exchange_connections"
    __table_args__ = (
        UniqueConstraint("user_id", "exchange_id", "key_fingerprint"),
        Index("ix_exchange_connections_user", "user_id"),
        CheckConstraint("status IN ('active','error','blocked')", name="status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    portfolio_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False
    )
    exchange_id: Mapped[str] = mapped_column(ForeignKey("exchanges.id"), nullable=False)
    label: Mapped[str] = mapped_column(String(80), nullable=False)
    api_key_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    api_secret_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    #: HMAC of the API key: detects the same key connected twice without storing it
    key_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    key_hint: Mapped[str] = mapped_column(String(8), nullable=False)
    #: active | error (last sync failed, retried) | blocked (key no longer read-only/valid)
    status: Mapped[str] = mapped_column(String(8), nullable=False, server_default="active")
    permissions: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    sync_cursor: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    reconciliation: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    sync_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ExchangeRecord(Base):
    __tablename__ = "exchange_records"
    __table_args__ = (
        UniqueConstraint("connection_id", "external_id"),
        Index("ix_exchange_records_connection_status", "connection_id", "status"),
        CheckConstraint("status IN ('pending','imported','needs_review')", name="status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("exchange_connections.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    external_id: Mapped[str] = mapped_column(String(128), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
