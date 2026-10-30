"""phase 1 foundation

Revision ID: fc22d47b7c75
Revises:
Create Date: 2026-10-27 22:06:05.428422
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "fc22d47b7c75"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cryptocurrencies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("image_url", sa.String(length=512), nullable=True),
        sa.Column("market_cap_rank", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cryptocurrencies")),
        sa.UniqueConstraint(
            "source", "source_id", name=op.f("uq_cryptocurrencies_source_source_id")
        ),
    )
    op.create_index(
        op.f("ix_cryptocurrencies_symbol"), "cryptocurrencies", ["symbol"], unique=False
    )
    op.create_table(
        "fx_rates",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("base_currency", sa.String(length=3), nullable=False),
        sa.Column("quote_currency", sa.String(length=3), nullable=False),
        sa.Column("rate", sa.Numeric(precision=24, scale=10), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("rate > 0", name=op.f("ck_fx_rates_rate_positive")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fx_rates")),
        sa.UniqueConstraint(
            "base_currency",
            "quote_currency",
            "observed_at",
            name=op.f("uq_fx_rates_base_currency_quote_currency_observed_at"),
        ),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("full_name", sa.String(length=120), nullable=False),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("mfa_secret_encrypted", sa.Text(), nullable=True),
        sa.Column("mfa_enabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "password_changed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint("email = lower(email)", name=op.f("ck_users_email_lowercase")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column(
            "context", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_audit_logs_user_id_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_logs")),
    )
    op.create_index(op.f("ix_audit_logs_action"), "audit_logs", ["action"], unique=False)
    op.create_index(
        "ix_audit_logs_user_created", "audit_logs", ["user_id", "created_at"], unique=False
    )
    op.create_table(
        "auth_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "purpose",
            sa.Enum("email_verification", "password_reset", name="auth_token_purpose"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_auth_tokens_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_auth_tokens_token_hash")),
    )
    op.create_index(
        "ix_auth_tokens_user_purpose", "auth_tokens", ["user_id", "purpose"], unique=False
    )
    op.create_table(
        "market_prices",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("cryptocurrency_id", sa.Uuid(), nullable=False),
        sa.Column("quote_currency", sa.String(length=3), nullable=False),
        sa.Column("price", sa.Numeric(precision=38, scale=18), nullable=False),
        sa.Column("market_cap", sa.Numeric(precision=38, scale=8), nullable=True),
        sa.Column("fully_diluted_valuation", sa.Numeric(precision=38, scale=8), nullable=True),
        sa.Column("total_volume", sa.Numeric(precision=38, scale=8), nullable=True),
        sa.Column("high_24h", sa.Numeric(precision=38, scale=18), nullable=True),
        sa.Column("low_24h", sa.Numeric(precision=38, scale=18), nullable=True),
        sa.Column("change_pct_1h", sa.Numeric(precision=18, scale=8), nullable=True),
        sa.Column("change_pct_24h", sa.Numeric(precision=18, scale=8), nullable=True),
        sa.Column("change_pct_7d", sa.Numeric(precision=18, scale=8), nullable=True),
        sa.Column("circulating_supply", sa.Numeric(precision=38, scale=8), nullable=True),
        sa.Column("total_supply", sa.Numeric(precision=38, scale=8), nullable=True),
        sa.Column("max_supply", sa.Numeric(precision=38, scale=8), nullable=True),
        sa.Column("ath", sa.Numeric(precision=38, scale=18), nullable=True),
        sa.Column("ath_change_pct", sa.Numeric(precision=18, scale=8), nullable=True),
        sa.Column("ath_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("price >= 0", name=op.f("ck_market_prices_price_non_negative")),
        sa.ForeignKeyConstraint(
            ["cryptocurrency_id"],
            ["cryptocurrencies.id"],
            name=op.f("fk_market_prices_cryptocurrency_id_cryptocurrencies"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_market_prices")),
        sa.UniqueConstraint(
            "cryptocurrency_id",
            "quote_currency",
            "source_updated_at",
            name=op.f("uq_market_prices_cryptocurrency_id_quote_currency_source_updated_at"),
        ),
    )
    op.create_index("ix_market_prices_fetched_at", "market_prices", ["fetched_at"], unique=False)
    op.create_table(
        "market_tickers",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("cryptocurrency_id", sa.Uuid(), nullable=False),
        sa.Column("quote_currency", sa.String(length=3), nullable=False),
        sa.Column("price", sa.Numeric(precision=38, scale=18), nullable=False),
        sa.Column("market_cap", sa.Numeric(precision=38, scale=8), nullable=True),
        sa.Column("fully_diluted_valuation", sa.Numeric(precision=38, scale=8), nullable=True),
        sa.Column("total_volume", sa.Numeric(precision=38, scale=8), nullable=True),
        sa.Column("high_24h", sa.Numeric(precision=38, scale=18), nullable=True),
        sa.Column("low_24h", sa.Numeric(precision=38, scale=18), nullable=True),
        sa.Column("change_pct_1h", sa.Numeric(precision=18, scale=8), nullable=True),
        sa.Column("change_pct_24h", sa.Numeric(precision=18, scale=8), nullable=True),
        sa.Column("change_pct_7d", sa.Numeric(precision=18, scale=8), nullable=True),
        sa.Column("circulating_supply", sa.Numeric(precision=38, scale=8), nullable=True),
        sa.Column("total_supply", sa.Numeric(precision=38, scale=8), nullable=True),
        sa.Column("max_supply", sa.Numeric(precision=38, scale=8), nullable=True),
        sa.Column("ath", sa.Numeric(precision=38, scale=18), nullable=True),
        sa.Column("ath_change_pct", sa.Numeric(precision=18, scale=8), nullable=True),
        sa.Column("ath_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("price >= 0", name=op.f("ck_market_tickers_price_non_negative")),
        sa.ForeignKeyConstraint(
            ["cryptocurrency_id"],
            ["cryptocurrencies.id"],
            name=op.f("fk_market_tickers_cryptocurrency_id_cryptocurrencies"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_market_tickers")),
        sa.UniqueConstraint(
            "cryptocurrency_id",
            "quote_currency",
            name=op.f("uq_market_tickers_cryptocurrency_id_quote_currency"),
        ),
    )
    op.create_table(
        "mfa_recovery_codes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_mfa_recovery_codes_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mfa_recovery_codes")),
        sa.UniqueConstraint("code_hash", name=op.f("uq_mfa_recovery_codes_code_hash")),
    )
    op.create_index(
        op.f("ix_mfa_recovery_codes_user_id"), "mfa_recovery_codes", ["user_id"], unique=False
    )
    op.create_table(
        "user_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_user_sessions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_sessions")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_user_sessions_token_hash")),
    )
    op.create_index(
        "ix_user_sessions_user_id_active", "user_sessions", ["user_id", "revoked_at"], unique=False
    )
    op.create_table(
        "user_settings",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("base_currency", sa.String(length=3), server_default="BRL", nullable=False),
        sa.Column("locale", sa.String(length=10), server_default="pt-BR", nullable=False),
        sa.Column(
            "timezone", sa.String(length=64), server_default="America/Sao_Paulo", nullable=False
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "base_currency IN ('BRL', 'USD')", name=op.f("ck_user_settings_base_currency_supported")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_user_settings_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_user_settings")),
    )


def downgrade() -> None:
    op.drop_table("user_settings")
    op.drop_index("ix_user_sessions_user_id_active", table_name="user_sessions")
    op.drop_table("user_sessions")
    op.drop_index(op.f("ix_mfa_recovery_codes_user_id"), table_name="mfa_recovery_codes")
    op.drop_table("mfa_recovery_codes")
    op.drop_table("market_tickers")
    op.drop_index("ix_market_prices_fetched_at", table_name="market_prices")
    op.drop_table("market_prices")
    op.drop_index("ix_auth_tokens_user_purpose", table_name="auth_tokens")
    op.drop_table("auth_tokens")
    op.drop_index("ix_audit_logs_user_created", table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_action"), table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_table("users")
    op.drop_table("fx_rates")
    op.drop_index(op.f("ix_cryptocurrencies_symbol"), table_name="cryptocurrencies")
    op.drop_table("cryptocurrencies")
    sa.Enum(name="auth_token_purpose").drop(op.get_bind(), checkfirst=True)
