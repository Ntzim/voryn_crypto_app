import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.models import AuditLog


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
    SESSION_REVOKED = "auth.session_revoked"
    PROFILE_UPDATED = "user.profile_updated"
    SETTINGS_UPDATED = "user.settings_updated"


def record(
    db: AsyncSession,
    action: str,
    *,
    user_id: uuid.UUID | None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    **context: Any,
) -> None:
    """Add an audit entry to the current unit of work (committed with the caller's change)."""
    db.add(
        AuditLog(
            user_id=user_id,
            action=action,
            ip_address=ip_address,
            user_agent=(user_agent or "")[:512] or None,
            context=context,
        )
    )
