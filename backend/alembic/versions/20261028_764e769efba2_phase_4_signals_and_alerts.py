"""phase 4 signals and alerts

Revision ID: 764e769efba2
Revises: a60c4daf465b
Create Date: 2026-10-28 20:56:57.119390
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "764e769efba2"
down_revision: str | None = "a60c4daf465b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "signal_strategies",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("key", sa.String(length=32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("weights", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("thresholds", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_signal_strategies")),
        sa.UniqueConstraint("key", "version", name=op.f("uq_signal_strategies_key_version")),
    )
    op.create_table(
        "alerts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "type",
            sa.Enum(
                "price_above",
                "price_below",
                "rsi_above",
                "rsi_below",
                "ma_cross",
                "volume_spike",
                "trend_change",
                "signal_change",
                "concentration",
                name="alert_type",
            ),
            nullable=False,
        ),
        sa.Column("cryptocurrency_id", sa.Uuid(), nullable=True),
        sa.Column("timeframe", sa.String(length=3), nullable=True),
        sa.Column(
            "params", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column("notify_email", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("cooldown_minutes", sa.Integer(), server_default="360", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("last_state", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("last_evaluated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_triggered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trigger_count", sa.Integer(), server_default="0", nullable=False),
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
            "timeframe IS NULL OR timeframe IN ('15m', '1h', '4h', '1d', '1w')",
            name=op.f("ck_alerts_timeframe_supported"),
        ),
        sa.CheckConstraint(
            "cooldown_minutes BETWEEN 15 AND 10080", name=op.f("ck_alerts_cooldown_range")
        ),
        sa.ForeignKeyConstraint(
            ["cryptocurrency_id"],
            ["cryptocurrencies.id"],
            name=op.f("fk_alerts_cryptocurrency_id_cryptocurrencies"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_alerts_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_alerts")),
    )
    op.create_index("ix_alerts_active", "alerts", ["is_active"], unique=False)
    op.create_index("ix_alerts_user_id", "alerts", ["user_id"], unique=False)
    op.create_table(
        "analysis_signals",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("cryptocurrency_id", sa.Uuid(), nullable=False),
        sa.Column("timeframe", sa.String(length=3), nullable=False),
        sa.Column("strategy_id", sa.Integer(), nullable=False),
        sa.Column("candle_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("reference_price", sa.Numeric(precision=38, scale=18), nullable=False),
        sa.Column("score", sa.Numeric(precision=5, scale=1), nullable=False),
        sa.Column("classification", sa.String(length=16), nullable=False),
        sa.Column("components", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("indicators", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("trend", sa.String(length=16), nullable=False),
        sa.Column("justification", sa.Text(), nullable=False),
        sa.Column("risks", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("invalidation", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("data_source", sa.String(length=64), nullable=False),
        sa.Column("data_fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("data_is_stale", sa.Boolean(), nullable=False),
        sa.Column("methodology_version", sa.String(length=16), nullable=False),
        sa.CheckConstraint(
            "classification IN ('buy_potential', 'neutral', 'attention', 'sell_potential')",
            name=op.f("ck_analysis_signals_classification_valid"),
        ),
        sa.CheckConstraint(
            "score >= 0 AND score <= 100", name=op.f("ck_analysis_signals_score_range")
        ),
        sa.ForeignKeyConstraint(
            ["cryptocurrency_id"],
            ["cryptocurrencies.id"],
            name=op.f("fk_analysis_signals_cryptocurrency_id_cryptocurrencies"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["strategy_id"],
            ["signal_strategies.id"],
            name=op.f("fk_analysis_signals_strategy_id_signal_strategies"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_analysis_signals")),
        sa.UniqueConstraint(
            "cryptocurrency_id",
            "timeframe",
            "strategy_id",
            "candle_time",
            name=op.f("uq_analysis_signals_cryptocurrency_id_timeframe_strategy_id_candle_time"),
        ),
    )
    op.create_index(
        "ix_analysis_signals_asset",
        "analysis_signals",
        ["cryptocurrency_id", "timeframe", "candle_time"],
        unique=False,
    )
    op.create_index(
        "ix_analysis_signals_latest",
        "analysis_signals",
        ["timeframe", "strategy_id", "candle_time"],
        unique=False,
    )
    op.create_table(
        "notifications",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("alert_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(length=16), server_default="alert", nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "data", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column("dedupe_key", sa.String(length=160), nullable=False),
        sa.Column(
            "channels", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["alert_id"],
            ["alerts.id"],
            name=op.f("fk_notifications_alert_id_alerts"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_notifications_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
        sa.UniqueConstraint(
            "user_id", "dedupe_key", name=op.f("uq_notifications_user_id_dedupe_key")
        ),
    )
    op.create_index(
        "ix_notifications_user_created", "notifications", ["user_id", "created_at"], unique=False
    )
    op.create_index(
        "ix_notifications_user_unread", "notifications", ["user_id", "read_at"], unique=False
    )

    strategies = sa.table(
        "signal_strategies",
        sa.column("key", sa.String),
        sa.column("version", sa.Integer),
        sa.column("name", sa.String),
        sa.column("weights", postgresql.JSONB),
        sa.column("thresholds", postgresql.JSONB),
        sa.column("is_active", sa.Boolean),
    )
    op.bulk_insert(
        strategies,
        [
            {
                "key": "voryn-core",
                "version": 1,
                "name": "Voryn Core v1",
                "weights": {
                    "trend": "0.25",
                    "momentum": "0.20",
                    "volume": "0.15",
                    "volatility": "0.15",
                    "levels": "0.15",
                    "market": "0.10",
                },
                "thresholds": {"buy": "65", "sell": "35"},
                "is_active": True,
            }
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_notifications_user_unread", table_name="notifications")
    op.drop_index("ix_notifications_user_created", table_name="notifications")
    op.drop_table("notifications")
    op.drop_index("ix_analysis_signals_latest", table_name="analysis_signals")
    op.drop_index("ix_analysis_signals_asset", table_name="analysis_signals")
    op.drop_table("analysis_signals")
    op.drop_index("ix_alerts_user_id", table_name="alerts")
    op.drop_index("ix_alerts_active", table_name="alerts")
    op.drop_table("alerts")
    op.drop_table("signal_strategies")
    sa.Enum(name="alert_type").drop(op.get_bind(), checkfirst=True)
