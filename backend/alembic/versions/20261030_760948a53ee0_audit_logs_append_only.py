"""audit logs append only

Revision ID: 760948a53ee0
Revises: 7e085c8bf0ab
Create Date: 2026-10-30

Adds a trigger; no data is changed. See app.modules.audit.models.APPEND_ONLY_FUNCTION.
The SQL is copied here rather than imported so this migration keeps working if the
model's definition changes later.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "760948a53ee0"
down_revision: str | None = "7e085c8bf0ab"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION audit_logs_append_only() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF OLD.created_at < now() - interval '365 days' THEN
                    RETURN OLD;
                END IF;
            ELSIF NEW.user_id IS NULL AND OLD.user_id IS NOT NULL
                AND (NEW.id, NEW.action, NEW.ip_address, NEW.user_agent, NEW.context,
                     NEW.created_at)
                    IS NOT DISTINCT FROM
                    (OLD.id, OLD.action, OLD.ip_address, OLD.user_agent, OLD.context,
                     OLD.created_at)
            THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION USING
                MESSAGE = 'audit_logs is append-only (' || TG_OP || ' refused)',
                ERRCODE = 'insufficient_privilege';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        "CREATE TRIGGER audit_logs_append_only BEFORE UPDATE OR DELETE ON audit_logs "
        "FOR EACH ROW EXECUTE FUNCTION audit_logs_append_only()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_logs_append_only ON audit_logs")
    op.execute("DROP FUNCTION IF EXISTS audit_logs_append_only()")
