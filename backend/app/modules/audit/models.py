import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DDL, BigInteger, DateTime, ForeignKey, Identity, Index, String, event, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

#: audit entries are kept this long, then pruned by the audit.prune task
AUDIT_RETENTION_DAYS = 365

# Append-only at the database level, so a bug or an injected statement in the application
# cannot rewrite or erase the trail. Allowed besides INSERT: the SET NULL of user_id when an
# account is deleted (anonymisation), and deleting entries past the retention period.
# The table owner can still drop the trigger: this guards the application, not the DBA.
APPEND_ONLY_FUNCTION = f"""
CREATE OR REPLACE FUNCTION audit_logs_append_only() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.created_at < now() - interval '{AUDIT_RETENTION_DAYS} days' THEN
            RETURN OLD;
        END IF;
    ELSIF NEW.user_id IS NULL AND OLD.user_id IS NOT NULL
        AND (NEW.id, NEW.action, NEW.ip_address, NEW.user_agent, NEW.context, NEW.created_at)
            IS NOT DISTINCT FROM
            (OLD.id, OLD.action, OLD.ip_address, OLD.user_agent, OLD.context, OLD.created_at)
    THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION USING
        MESSAGE = 'audit_logs is append-only (' || TG_OP || ' refused)',
        ERRCODE = 'insufficient_privilege';
END;
$$ LANGUAGE plpgsql
"""
APPEND_ONLY_TRIGGER = """
CREATE TRIGGER audit_logs_append_only
    BEFORE UPDATE OR DELETE ON audit_logs
    FOR EACH ROW EXECUTE FUNCTION audit_logs_append_only()
"""


class AuditLog(Base):
    """Append-only security/audit trail. Never store secrets or full tokens in `context`."""

    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_logs_user_created", "user_id", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    # SET NULL keeps the trail after account deletion (LGPD: context holds no PII beyond IP).
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    ip_address: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(512))
    context: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# Databases built from the models (the test-suite) get the same guard as migrated ones.
for _statement in (APPEND_ONLY_FUNCTION, APPEND_ONLY_TRIGGER):
    event.listen(AuditLog.__table__, "after_create", DDL(_statement))  # type: ignore[no-untyped-call]
