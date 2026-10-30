import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_sessionmaker
from app.modules.audit.models import AUDIT_RETENTION_DAYS, AuditLog


class AuditAction:
    USER_REGISTERED = "user.registered"
    EMAIL_VERIFIED = "auth.email_verified"
    LOGIN_SUCCEEDED = "auth.login_succeeded"
    LOGIN_FAILED = "auth.login_failed"
    LOGOUT = "auth.logout"
    PASSWORD_RESET_REQUESTED = "auth.password_reset_requested"
    PASSWORD_RESET = "auth.password_reset"
    PASSWORD_CHANGED = "auth.password_changed"
    MFA_ENABLED = "auth.mfa_enabled"
    MFA_DISABLED = "auth.mfa_disabled"
    MFA_RECOVERY_CODE_USED = "auth.mfa_recovery_code_used"
    MFA_RECOVERY_CODES_REGENERATED = "auth.mfa_recovery_codes_regenerated"
    SESSION_REVOKED = "auth.session_revoked"
    PROFILE_UPDATED = "user.profile_updated"
    SETTINGS_UPDATED = "user.settings_updated"
    #: a signed-in user asked for a resource that exists but belongs to someone else
    ACCESS_DENIED = "authz.access_denied"
    EXCHANGE_CONNECTED = "exchange.connected"
    EXCHANGE_DISCONNECTED = "exchange.disconnected"
    EXCHANGE_SYNC_FAILED = "exchange.sync_failed"
    #: the key lost its read-only status or was revoked at the exchange
    EXCHANGE_BLOCKED = "exchange.blocked"


def _entry(
    action: str,
    user_id: uuid.UUID | None,
    ip_address: str | None,
    user_agent: str | None,
    context: dict[str, Any],
) -> AuditLog:
    request_id = structlog.contextvars.get_contextvars().get("request_id")
    if request_id:
        context = {"request_id": request_id, **context}
    return AuditLog(
        user_id=user_id,
        action=action,
        ip_address=ip_address,
        user_agent=(user_agent or "")[:512] or None,
        context=context,
    )


def record(
    db: AsyncSession,
    action: str,
    *,
    user_id: uuid.UUID | None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    **context: Any,
) -> None:
    """Add an audit entry to the current unit of work (committed with the caller's change).

    The request id is added automatically so an entry can be matched with the access log.
    """
    db.add(_entry(action, user_id, ip_address, user_agent, context))


async def record_now(
    action: str,
    *,
    user_id: uuid.UUID | None,
    ip_address: str | None = None,
    **context: Any,
) -> None:
    """Commit an entry in its own transaction, for events whose request then fails
    (the caller's unit of work is rolled back with the error response)."""
    async with get_sessionmaker()() as session:
        session.add(_entry(action, user_id, ip_address, None, context))
        await session.commit()


async def prune(db: AsyncSession) -> int:
    """Delete entries past the retention period (the only deletion the trigger allows)."""
    cutoff = datetime.now(UTC) - timedelta(days=AUDIT_RETENTION_DAYS)
    result = await db.execute(delete(AuditLog).where(AuditLog.created_at < cutoff))
    await db.commit()
    return int(result.rowcount)  # type: ignore[attr-defined]
