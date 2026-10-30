"""signal data quality

Revision ID: 7e085c8bf0ab
Revises: 77094b34d04b
Create Date: 2026-10-30 12:16:48.148987

Additive only: two columns with defaults, existing rows graded from data_is_stale.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "7e085c8bf0ab"
down_revision: str | None = "77094b34d04b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "analysis_signals",
        sa.Column("data_quality", sa.String(length=16), server_default="valid", nullable=False),
    )
    op.add_column(
        "analysis_signals",
        sa.Column(
            "quality_reasons",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
    )
    op.execute(
        "UPDATE analysis_signals SET data_quality = 'stale', "
        "quality_reasons = '[\"Dados de preço desatualizados na geração.\"]'::jsonb "
        "WHERE data_is_stale"
    )
    op.create_check_constraint(
        "data_quality_valid",
        "analysis_signals",
        "data_quality IN ('valid', 'stale', 'incomplete', 'anomalous')",
    )


def downgrade() -> None:
    op.drop_constraint("data_quality_valid", "analysis_signals", type_="check")
    op.drop_column("analysis_signals", "quality_reasons")
    op.drop_column("analysis_signals", "data_quality")
