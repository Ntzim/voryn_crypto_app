"""multimarket instruments

Revision ID: 3b9d2f61c0a4
Revises: 760948a53ee0
Create Date: 2026-10-31

Additive and reversible: `cryptocurrencies` gains market/asset_type/exchange/currency/sector
(existing rows backfilled through the server defaults as CRYPTO/USD) and `market_tickers`
gains the declared quote delay. No table or column is renamed.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "3b9d2f61c0a4"
down_revision: str | None = "760948a53ee0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "cryptocurrencies",
        sa.Column("market", sa.String(8), server_default="CRYPTO", nullable=False),
    )
    op.add_column(
        "cryptocurrencies",
        sa.Column("asset_type", sa.String(8), server_default="CRYPTO", nullable=False),
    )
    op.add_column("cryptocurrencies", sa.Column("exchange", sa.String(8), nullable=True))
    op.add_column(
        "cryptocurrencies",
        sa.Column("currency", sa.String(3), server_default="USD", nullable=False),
    )
    op.add_column("cryptocurrencies", sa.Column("sector", sa.String(128), nullable=True))
    op.create_check_constraint(
        "market_supported", "cryptocurrencies", "market IN ('CRYPTO', 'B3', 'US')"
    )
    op.create_check_constraint(
        "asset_type_supported",
        "cryptocurrencies",
        "asset_type IN ('CRYPTO', 'STOCK', 'FII', 'ETF', 'BDR')",
    )
    op.create_index("ix_cryptocurrencies_market", "cryptocurrencies", ["market"])
    op.create_index(
        "uq_instruments_market_symbol",
        "cryptocurrencies",
        ["market", "symbol"],
        unique=True,
        postgresql_where=sa.text("market <> 'CRYPTO'"),
    )
    op.add_column(
        "market_tickers",
        sa.Column("delay_seconds", sa.Integer(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    # Non-crypto instruments cannot be represented by the old schema.
    op.execute("DELETE FROM cryptocurrencies WHERE market <> 'CRYPTO'")
    op.drop_column("market_tickers", "delay_seconds")
    op.drop_index("uq_instruments_market_symbol", table_name="cryptocurrencies")
    op.drop_index("ix_cryptocurrencies_market", table_name="cryptocurrencies")
    op.drop_constraint("asset_type_supported", "cryptocurrencies", type_="check")
    op.drop_constraint("market_supported", "cryptocurrencies", type_="check")
    for column in ("sector", "currency", "exchange", "asset_type", "market"):
        op.drop_column("cryptocurrencies", column)
