"""Portfolio storage.

Transactions are the single source of truth; positions and returns are derived by the
engine on read, so editing a past transaction can never leave stale aggregates behind.

Each transaction stores the USD→BRL rate in force when it was executed (official PTAX for
past dates, live rate for recent ones). That makes cost basis and P/L exact in both BRL
and USD, independent of the currency the user traded in.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin
from app.modules.market_data.models import Amount, Price
from app.modules.portfolio.engine import TxType

Quantity = Numeric(38, 18)


#: Seeded by the phase-2 migration (kept there as a frozen copy); used by tests.
DEFAULT_EXCHANGES = [
    ("binance", "Binance", "exchange"),
    ("coinbase", "Coinbase", "exchange"),
    ("kraken", "Kraken", "exchange"),
    ("mercado-bitcoin", "Mercado Bitcoin", "exchange"),
    ("foxbit", "Foxbit", "exchange"),
    ("novadax", "NovaDAX", "exchange"),
    ("bitso", "Bitso", "exchange"),
    ("bybit", "Bybit", "exchange"),
    ("okx", "OKX", "exchange"),
    ("kucoin", "KuCoin", "exchange"),
    ("bitget", "Bitget", "exchange"),
    ("carteira", "Carteira própria", "wallet"),
    ("outra", "Outra", "other"),
]


class Exchange(Base):
    """Catalogue of venues/wallets a transaction can be attributed to (seeded by migration)."""

    __tablename__ = "exchanges"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # slug, e.g. "binance"
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # exchange | wallet | other


class Portfolio(TimestampMixin, Base):
    __tablename__ = "portfolios"
    __table_args__ = (Index("ix_portfolios_user_id", "user_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)


class Transaction(TimestampMixin, Base):
    __tablename__ = "transactions"
    __table_args__ = (
        Index("ix_transactions_portfolio_executed", "portfolio_id", "executed_at"),
        Index("ix_transactions_user_id", "user_id"),
        UniqueConstraint("portfolio_id", "source", "external_id"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_price IS NULL OR unit_price >= 0", name="unit_price_non_negative"),
        CheckConstraint("fee_amount >= 0", name="fee_non_negative"),
        CheckConstraint("fee_quantity >= 0", name="fee_quantity_non_negative"),
        CheckConstraint("fx_usd_brl > 0", name="fx_positive"),
        CheckConstraint("quote_currency IN ('BRL', 'USD')", name="quote_supported"),
        CheckConstraint(
            "(type = 'conversion') = (to_cryptocurrency_id IS NOT NULL AND to_quantity > 0)",
            name="conversion_target",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    portfolio_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False
    )
    # Denormalized owner for cheap, explicit tenant filtering.
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[TxType] = mapped_column(
        Enum(TxType, name="transaction_type", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    cryptocurrency_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cryptocurrencies.id", ondelete="RESTRICT"), nullable=False
    )
    quantity: Mapped[Decimal] = mapped_column(Quantity, nullable=False)
    unit_price: Mapped[Decimal | None] = mapped_column(Price)
    quote_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    #: quantity × unit_price in quote_currency (stored for display and audit).
    gross_amount: Mapped[Decimal | None] = mapped_column(Amount)
    fee_amount: Mapped[Decimal] = mapped_column(Amount, nullable=False, server_default="0")
    fee_quantity: Mapped[Decimal] = mapped_column(Quantity, nullable=False, server_default="0")
    to_cryptocurrency_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("cryptocurrencies.id", ondelete="RESTRICT")
    )
    to_quantity: Mapped[Decimal | None] = mapped_column(Quantity)
    fx_usd_brl: Mapped[Decimal] = mapped_column(Numeric(24, 10), nullable=False)
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    exchange_id: Mapped[str | None] = mapped_column(ForeignKey("exchanges.id"))
    to_exchange_id: Mapped[str | None] = mapped_column(ForeignKey("exchanges.id"))
    notes: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(16), nullable=False, server_default="manual")
    #: dedupe key: the CSV row fingerprint or the exchange's trade id.
    external_id: Mapped[str | None] = mapped_column(String(128))
