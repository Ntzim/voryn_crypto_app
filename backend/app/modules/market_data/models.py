"""Market data storage.

- `cryptocurrencies`: asset catalogue, keyed by (source, source_id) because symbols are
  not unique across the crypto universe.
- `market_tickers`: latest observed quote per asset (upserted every sync, cheap to query).
- `market_prices`: append-only history of quotes, deduplicated on the provider timestamp,
  pruned after MARKET_HISTORY_RETENTION_DAYS (long-range history comes from candles).
- `fx_rates`: fiat conversion rates (USD→BRL) with observation time.

Monetary columns use NUMERIC; floats are never used for financial values.
"""

import uuid
from datetime import datetime
from decimal import Decimal

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
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, TimestampMixin

# Prices of micro-cap tokens can have many leading zeros; caps/volumes can exceed 1e12.
Price = Numeric(38, 18)
Amount = Numeric(38, 8)
Percent = Numeric(18, 8)


class Cryptocurrency(TimestampMixin, Base):
    __tablename__ = "cryptocurrencies"
    __table_args__ = (UniqueConstraint("source", "source_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[str] = mapped_column(String(128), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    image_url: Mapped[str | None] = mapped_column(String(512))
    market_cap_rank: Mapped[int | None] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    ticker: Mapped["MarketTicker | None"] = relationship(
        back_populates="cryptocurrency", lazy="raise", uselist=False
    )


class _QuoteColumns:
    quote_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    price: Mapped[Decimal] = mapped_column(Price, nullable=False)
    market_cap: Mapped[Decimal | None] = mapped_column(Amount)
    fully_diluted_valuation: Mapped[Decimal | None] = mapped_column(Amount)
    total_volume: Mapped[Decimal | None] = mapped_column(Amount)
    high_24h: Mapped[Decimal | None] = mapped_column(Price)
    low_24h: Mapped[Decimal | None] = mapped_column(Price)
    change_pct_1h: Mapped[Decimal | None] = mapped_column(Percent)
    change_pct_24h: Mapped[Decimal | None] = mapped_column(Percent)
    change_pct_7d: Mapped[Decimal | None] = mapped_column(Percent)
    circulating_supply: Mapped[Decimal | None] = mapped_column(Amount)
    total_supply: Mapped[Decimal | None] = mapped_column(Amount)
    max_supply: Mapped[Decimal | None] = mapped_column(Amount)
    ath: Mapped[Decimal | None] = mapped_column(Price)
    ath_change_pct: Mapped[Decimal | None] = mapped_column(Percent)
    ath_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    # When the provider says the quote was computed vs. when we fetched it.
    source_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MarketTicker(_QuoteColumns, Base):
    __tablename__ = "market_tickers"
    __table_args__ = (
        UniqueConstraint("cryptocurrency_id", "quote_currency"),
        CheckConstraint("price >= 0", name="price_non_negative"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    cryptocurrency_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cryptocurrencies.id", ondelete="CASCADE"), nullable=False
    )

    cryptocurrency: Mapped[Cryptocurrency] = relationship(back_populates="ticker", lazy="raise")


class MarketPrice(_QuoteColumns, Base):
    __tablename__ = "market_prices"
    __table_args__ = (
        UniqueConstraint("cryptocurrency_id", "quote_currency", "source_updated_at"),
        CheckConstraint("price >= 0", name="price_non_negative"),
        Index("ix_market_prices_fetched_at", "fetched_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    cryptocurrency_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cryptocurrencies.id", ondelete="CASCADE"), nullable=False
    )


class FxRate(Base):
    __tablename__ = "fx_rates"
    __table_args__ = (
        UniqueConstraint("base_currency", "quote_currency", "observed_at"),
        CheckConstraint("rate > 0", name="rate_positive"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    base_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    quote_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    rate: Mapped[Decimal] = mapped_column(Numeric(24, 10), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
