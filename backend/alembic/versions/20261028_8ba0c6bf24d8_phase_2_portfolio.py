"""phase 2 portfolio

Revision ID: 8ba0c6bf24d8
Revises: fc22d47b7c75
Create Date: 2026-10-28 20:00:07.888387
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "8ba0c6bf24d8"
down_revision: str | None = "fc22d47b7c75"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "exchanges",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_exchanges")),
    )
    op.create_table(
        "daily_prices",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("cryptocurrency_id", sa.Uuid(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("close", sa.Numeric(precision=38, scale=18), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("close >= 0", name=op.f("ck_daily_prices_close_non_negative")),
        sa.ForeignKeyConstraint(
            ["cryptocurrency_id"],
            ["cryptocurrencies.id"],
            name=op.f("fk_daily_prices_cryptocurrency_id_cryptocurrencies"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_daily_prices")),
        sa.UniqueConstraint(
            "cryptocurrency_id", "day", name=op.f("uq_daily_prices_cryptocurrency_id_day")
        ),
    )
    op.create_table(
        "portfolios",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_portfolios_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_portfolios")),
    )
    op.create_index("ix_portfolios_user_id", "portfolios", ["user_id"], unique=False)
    op.create_table(
        "transactions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("portfolio_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "type",
            sa.Enum(
                "buy",
                "sell",
                "deposit",
                "withdrawal",
                "transfer",
                "fee",
                "conversion",
                name="transaction_type",
            ),
            nullable=False,
        ),
        sa.Column("cryptocurrency_id", sa.Uuid(), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=38, scale=18), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=38, scale=18), nullable=True),
        sa.Column("quote_currency", sa.String(length=3), nullable=False),
        sa.Column("gross_amount", sa.Numeric(precision=38, scale=8), nullable=True),
        sa.Column(
            "fee_amount", sa.Numeric(precision=38, scale=8), server_default="0", nullable=False
        ),
        sa.Column(
            "fee_quantity", sa.Numeric(precision=38, scale=18), server_default="0", nullable=False
        ),
        sa.Column("to_cryptocurrency_id", sa.Uuid(), nullable=True),
        sa.Column("to_quantity", sa.Numeric(precision=38, scale=18), nullable=True),
        sa.Column("fx_usd_brl", sa.Numeric(precision=24, scale=10), nullable=False),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("exchange_id", sa.String(length=32), nullable=True),
        sa.Column("to_exchange_id", sa.String(length=32), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=16), server_default="manual", nullable=False),
        sa.Column("external_id", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(type = 'conversion') = (to_cryptocurrency_id IS NOT NULL AND to_quantity > 0)",
            name=op.f("ck_transactions_conversion_target"),
        ),
        sa.CheckConstraint(
            "quote_currency IN ('BRL', 'USD')", name=op.f("ck_transactions_quote_supported")
        ),
        sa.CheckConstraint("fee_amount >= 0", name=op.f("ck_transactions_fee_non_negative")),
        sa.CheckConstraint(
            "fee_quantity >= 0", name=op.f("ck_transactions_fee_quantity_non_negative")
        ),
        sa.CheckConstraint("fx_usd_brl > 0", name=op.f("ck_transactions_fx_positive")),
        sa.CheckConstraint("quantity > 0", name=op.f("ck_transactions_quantity_positive")),
        sa.CheckConstraint(
            "unit_price IS NULL OR unit_price >= 0",
            name=op.f("ck_transactions_unit_price_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["cryptocurrency_id"],
            ["cryptocurrencies.id"],
            name=op.f("fk_transactions_cryptocurrency_id_cryptocurrencies"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["exchange_id"], ["exchanges.id"], name=op.f("fk_transactions_exchange_id_exchanges")
        ),
        sa.ForeignKeyConstraint(
            ["portfolio_id"],
            ["portfolios.id"],
            name=op.f("fk_transactions_portfolio_id_portfolios"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["to_cryptocurrency_id"],
            ["cryptocurrencies.id"],
            name=op.f("fk_transactions_to_cryptocurrency_id_cryptocurrencies"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["to_exchange_id"],
            ["exchanges.id"],
            name=op.f("fk_transactions_to_exchange_id_exchanges"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_transactions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_transactions")),
        sa.UniqueConstraint(
            "portfolio_id",
            "source",
            "external_id",
            name=op.f("uq_transactions_portfolio_id_source_external_id"),
        ),
    )
    op.create_index(
        "ix_transactions_portfolio_executed",
        "transactions",
        ["portfolio_id", "executed_at"],
        unique=False,
    )
    op.create_index("ix_transactions_user_id", "transactions", ["user_id"], unique=False)

    exchanges = sa.table(
        "exchanges",
        sa.column("id", sa.String),
        sa.column("name", sa.String),
        sa.column("kind", sa.String),
    )
    op.bulk_insert(
        exchanges,
        [
            {"id": "binance", "name": "Binance", "kind": "exchange"},
            {"id": "coinbase", "name": "Coinbase", "kind": "exchange"},
            {"id": "kraken", "name": "Kraken", "kind": "exchange"},
            {"id": "mercado-bitcoin", "name": "Mercado Bitcoin", "kind": "exchange"},
            {"id": "foxbit", "name": "Foxbit", "kind": "exchange"},
            {"id": "novadax", "name": "NovaDAX", "kind": "exchange"},
            {"id": "bitso", "name": "Bitso", "kind": "exchange"},
            {"id": "bybit", "name": "Bybit", "kind": "exchange"},
            {"id": "okx", "name": "OKX", "kind": "exchange"},
            {"id": "kucoin", "name": "KuCoin", "kind": "exchange"},
            {"id": "bitget", "name": "Bitget", "kind": "exchange"},
            {"id": "carteira", "name": "Carteira própria", "kind": "wallet"},
            {"id": "outra", "name": "Outra", "kind": "other"},
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_transactions_user_id", table_name="transactions")
    op.drop_index("ix_transactions_portfolio_executed", table_name="transactions")
    op.drop_table("transactions")
    op.drop_index("ix_portfolios_user_id", table_name="portfolios")
    op.drop_table("portfolios")
    op.drop_table("daily_prices")
    op.drop_table("exchanges")
    sa.Enum(name="transaction_type").drop(op.get_bind(), checkfirst=True)
