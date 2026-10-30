"""phase 3 market intelligence

Revision ID: a60c4daf465b
Revises: 8ba0c6bf24d8
Create Date: 2026-10-28 20:28:53.727845
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a60c4daf465b"
down_revision: str | None = "8ba0c6bf24d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "historical_candles",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("cryptocurrency_id", sa.Uuid(), nullable=False),
        sa.Column("timeframe", sa.String(length=3), nullable=False),
        sa.Column("open_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open", sa.Numeric(precision=38, scale=18), nullable=False),
        sa.Column("high", sa.Numeric(precision=38, scale=18), nullable=False),
        sa.Column("low", sa.Numeric(precision=38, scale=18), nullable=False),
        sa.Column("close", sa.Numeric(precision=38, scale=18), nullable=False),
        sa.Column("volume", sa.Numeric(precision=38, scale=8), nullable=False),
        sa.Column("quote_volume", sa.Numeric(precision=38, scale=8), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("source_symbol", sa.String(length=32), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "timeframe IN ('15m', '1h', '4h', '1d', '1w')",
            name=op.f("ck_historical_candles_timeframe_supported"),
        ),
        sa.CheckConstraint(
            "high >= low AND low > 0 AND volume >= 0",
            name=op.f("ck_historical_candles_ohlc_consistent"),
        ),
        sa.ForeignKeyConstraint(
            ["cryptocurrency_id"],
            ["cryptocurrencies.id"],
            name=op.f("fk_historical_candles_cryptocurrency_id_cryptocurrencies"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_historical_candles")),
        sa.UniqueConstraint(
            "cryptocurrency_id",
            "timeframe",
            "open_time",
            name=op.f("uq_historical_candles_cryptocurrency_id_timeframe_open_time"),
        ),
    )
    op.create_table(
        "watchlists",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=40), nullable=False),
        sa.Column("is_default", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_watchlists_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_watchlists")),
        sa.UniqueConstraint("user_id", "name", name=op.f("uq_watchlists_user_id_name")),
    )
    op.create_index(op.f("ix_watchlists_user_id"), "watchlists", ["user_id"], unique=False)
    op.create_index(
        "uq_watchlists_one_default",
        "watchlists",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )
    op.create_table(
        "watchlist_assets",
        sa.Column("watchlist_id", sa.Uuid(), nullable=False),
        sa.Column("cryptocurrency_id", sa.Uuid(), nullable=False),
        sa.Column(
            "added_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["cryptocurrency_id"],
            ["cryptocurrencies.id"],
            name=op.f("fk_watchlist_assets_cryptocurrency_id_cryptocurrencies"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["watchlist_id"],
            ["watchlists.id"],
            name=op.f("fk_watchlist_assets_watchlist_id_watchlists"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "watchlist_id", "cryptocurrency_id", name=op.f("pk_watchlist_assets")
        ),
    )


def downgrade() -> None:
    op.drop_table("watchlist_assets")
    op.drop_index(
        "uq_watchlists_one_default", table_name="watchlists", postgresql_where=sa.text("is_default")
    )
    op.drop_index(op.f("ix_watchlists_user_id"), table_name="watchlists")
    op.drop_table("watchlists")
    op.drop_table("historical_candles")
