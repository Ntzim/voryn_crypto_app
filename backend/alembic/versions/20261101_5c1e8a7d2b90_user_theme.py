"""user theme preference

Revision ID: 5c1e8a7d2b90
Revises: 3b9d2f61c0a4
Create Date: 2026-11-01

Additive: existing users get "system" (follow the device setting).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "5c1e8a7d2b90"
down_revision: str | None = "3b9d2f61c0a4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user_settings",
        sa.Column("theme", sa.String(8), server_default="system", nullable=False),
    )
    op.create_check_constraint(
        "theme_supported", "user_settings", "theme IN ('system', 'light', 'dark')"
    )


def downgrade() -> None:
    op.drop_constraint("theme_supported", "user_settings", type_="check")
    op.drop_column("user_settings", "theme")
