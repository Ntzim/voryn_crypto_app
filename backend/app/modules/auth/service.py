"""Authentication use-cases: registration, login (+2FA), sessions, e-mail tokens, passwords.

Security properties:
- Responses never reveal whether an e-mail is registered (register / forgot / resend).
- Password hashing runs in a worker thread so argon2 never blocks the event loop.
- Session, e-mail and recovery tokens are stored as HMAC digests only.
- Brute force is throttled per IP and per account (Redis counters).
"""

import asyncio
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core import rate_limit, security_events
from app.core.config import get_settings
from app.core.crypto import decrypt, encrypt
from app.core.email import deliver
from app.core.errors import AppError, ConflictError, NotFoundError, RateLimitedError
from app.core.redis import get_redis
from app.core.security import (
    generate_token,
    hash_password,
    hash_token,
    password_needs_rehash,
    verify_password,
)
from app.modules.audit.service import AuditAction, record
from app.modules.auth import emails, mfa
from app.modules.auth.models import AuthToken, MfaRecoveryCode, TokenPurpose, UserSession
from app.modules.auth.schemas import LoginIn, PasswordResetIn, RegisterIn
from app.modules.users.models import User, UserSettings

MFA_CHALLENGE_TTL = 300
MFA_SETUP_TTL = 600
SESSION_TOUCH_INTERVAL = timedelta(minutes=5)
LOGIN_ACCOUNT_FAILURES = 5
LOGIN_ACCOUNT_WINDOW = 15 * 60
# Second-factor failures per account, across challenges and IPs: a new challenge only
# costs the correct password, so a per-challenge cap alone allows unlimited guessing.
MFA_ACCOUNT_FAILURES = 10
MFA_ACCOUNT_WINDOW = 60 * 60


class InvalidCredentialsError(AppError):
    status_code = 401
    code = "invalid_credentials"
    message = "E-mail ou senha incorretos."


class EmailNotVerifiedError(AppError):
    status_code = 403
    code = "email_not_verified"
    message = "Confirme seu e-mail antes de entrar. Enviamos um link para sua caixa de entrada."


class InvalidTokenError(AppError):
    status_code = 400
    code = "invalid_token"
    message = "Link inválido ou expirado. Solicite um novo."


class InvalidMfaCodeError(AppError):
    status_code = 401
    code = "invalid_mfa_code"
    message = "Código de verificação inválido."


@dataclass(frozen=True, slots=True)
class RequestMeta:
    ip: str
    user_agent: str | None


@dataclass(frozen=True, slots=True)
class LoginResult:
    user: User | None = None
    session_token: str | None = None
    mfa_token: str | None = None


def utcnow() -> datetime:
    return datetime.now(UTC)


def _audit(
    db: AsyncSession, action: str, user_id: uuid.UUID | None, meta: RequestMeta, **ctx: object
) -> None:
    record(db, action, user_id=user_id, ip_address=meta.ip, user_agent=meta.user_agent, **ctx)


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(
        select(User).where(User.email == email).options(selectinload(User.settings))
    )
    return result.scalar_one_or_none()


async def get_user(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    result = await db.execute(
        select(User).where(User.id == user_id).options(selectinload(User.settings))
    )
    return result.scalar_one_or_none()


# --------------------------------------------------------------------------- tokens


async def _issue_token(
    db: AsyncSession, user_id: uuid.UUID, purpose: TokenPurpose, ttl: timedelta
) -> str:
    now = utcnow()
    # Only the most recent link of each purpose stays valid.
    await db.execute(
        update(AuthToken)
        .where(
            AuthToken.user_id == user_id,
            AuthToken.purpose == purpose,
            AuthToken.consumed_at.is_(None),
        )
        .values(consumed_at=now)
    )
    token = generate_token()
    db.add(
        AuthToken(
            user_id=user_id, purpose=purpose, token_hash=hash_token(token), expires_at=now + ttl
        )
    )
    return token


async def _consume_token(db: AsyncSession, token: str, purpose: TokenPurpose) -> AuthToken:
    now = utcnow()
    result = await db.execute(
        select(AuthToken)
        .where(
            AuthToken.token_hash == hash_token(token),
            AuthToken.purpose == purpose,
            AuthToken.consumed_at.is_(None),
            AuthToken.expires_at > now,
        )
        .with_for_update()
    )
    record_ = result.scalar_one_or_none()
    if record_ is None:
        raise InvalidTokenError()
    record_.consumed_at = now
    return record_


# --------------------------------------------------------------------------- registration


async def register(db: AsyncSession, data: RegisterIn, meta: RequestMeta) -> None:
    await rate_limit.enforce(f"register:ip:{meta.ip}", 5, 3600)
    # Hash before the existence check so both paths cost the same time.
    password_hash = await asyncio.to_thread(hash_password, data.password)
    existing = await get_user_by_email(db, data.email)
    if existing is not None:
        await _notify_existing_account(data.email)
        return

    user = User(email=data.email, password_hash=password_hash, full_name=data.full_name)
    user.settings = UserSettings()
    db.add(user)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()  # concurrent registration of the same e-mail
        await _notify_existing_account(data.email)
        return
    token = await _issue_token(
        db,
        user.id,
        TokenPurpose.EMAIL_VERIFICATION,
        timedelta(hours=get_settings().email_verification_ttl_hours),
    )
    _audit(db, AuditAction.USER_REGISTERED, user.id, meta)
    await db.commit()
    await deliver(emails.verification_email(user.email, user.full_name, token))


async def _notify_existing_account(email: str) -> None:
    if (await rate_limit.hit(f"register:exists:{email}", 1, 3600)).allowed:
        await deliver(emails.existing_account_email(email))


async def verify_email(db: AsyncSession, token: str, meta: RequestMeta) -> None:
    await rate_limit.enforce(f"verify:ip:{meta.ip}", 20, 3600)
    auth_token = await _consume_token(db, token, TokenPurpose.EMAIL_VERIFICATION)
    user = await db.get(User, auth_token.user_id)
    if user is not None and user.email_verified_at is None:
        user.email_verified_at = utcnow()
        _audit(db, AuditAction.EMAIL_VERIFIED, user.id, meta)
    await db.commit()


async def resend_verification(db: AsyncSession, email: str, meta: RequestMeta) -> None:
    await rate_limit.enforce(f"resend:ip:{meta.ip}", 5, 3600)
    user = await get_user_by_email(db, email)
    if user is None or user.email_verified_at is not None or not user.is_active:
        return
    if not (await rate_limit.hit(f"resend:email:{email}", 3, 3600)).allowed:
        return
    token = await _issue_token(
        db,
        user.id,
        TokenPurpose.EMAIL_VERIFICATION,
        timedelta(hours=get_settings().email_verification_ttl_hours),
    )
    await db.commit()
    await deliver(emails.verification_email(user.email, user.full_name, token))


# --------------------------------------------------------------------------- login


async def login(db: AsyncSession, data: LoginIn, meta: RequestMeta) -> LoginResult:
    await rate_limit.enforce(f"login:ip:{meta.ip}", 20, 600)
    fail_key = f"login:fail:{data.email}"
    failures, ttl = await rate_limit.peek(fail_key)
    if failures >= LOGIN_ACCOUNT_FAILURES * get_settings().rate_limit_scale:
        raise RateLimitedError(
            ttl, "Muitas tentativas para esta conta. Aguarde alguns minutos e tente novamente."
        )

    user = await get_user_by_email(db, data.email)
    valid = await asyncio.to_thread(
        verify_password, user.password_hash if user else None, data.password
    )
    if user is None or not valid or not user.is_active:
        await rate_limit.hit(fail_key, LOGIN_ACCOUNT_FAILURES, LOGIN_ACCOUNT_WINDOW)
        _audit(db, AuditAction.LOGIN_FAILED, user.id if user else None, meta, reason="credentials")
        await db.commit()
        await security_events.emit("login_failed", reason="credentials", ip=meta.ip)
        raise InvalidCredentialsError()

    await rate_limit.reset(fail_key)
    if password_needs_rehash(user.password_hash):
        user.password_hash = await asyncio.to_thread(hash_password, data.password)
        await db.commit()
    if user.email_verified_at is None:
        raise EmailNotVerifiedError()

    if user.mfa_enabled:
        mfa_token = generate_token()
        await get_redis().set(
            f"mfa_challenge:{hash_token(mfa_token)}",
            json.dumps({"user_id": str(user.id)}),
            ex=MFA_CHALLENGE_TTL,
        )
        return LoginResult(mfa_token=mfa_token)
    return await _complete_login(db, user, meta, method="password")


async def login_with_mfa(
    db: AsyncSession, mfa_token: str, code: str, meta: RequestMeta
) -> LoginResult:
    redis = get_redis()
    key = f"mfa_challenge:{hash_token(mfa_token)}"
    raw = await redis.get(key)
    if raw is None:
        raise AppError(
            "A verificação expirou. Entre novamente.", code="mfa_challenge_expired", status_code=401
        )
    attempts = await redis.incr(f"{key}:attempts")
    await redis.expire(f"{key}:attempts", MFA_CHALLENGE_TTL)
    if attempts > 5:
        await redis.delete(key)
        raise RateLimitedError(MFA_CHALLENGE_TTL, "Muitas tentativas. Entre novamente.")

    user = await get_user(db, uuid.UUID(json.loads(raw)["user_id"]))
    if user is None or not user.is_active or not user.mfa_enabled:
        await redis.delete(key)
        raise InvalidCredentialsError()
    fail_key = f"mfa_fail:{user.id}"
    failures, ttl = await rate_limit.peek(fail_key)
    if failures >= MFA_ACCOUNT_FAILURES * get_settings().rate_limit_scale:
        await redis.delete(key)
        raise RateLimitedError(
            ttl, "Muitas tentativas de verificação nesta conta. Aguarde e tente novamente."
        )
    if not await _verify_second_factor(db, user, code, meta):
        result = await rate_limit.hit(fail_key, MFA_ACCOUNT_FAILURES, MFA_ACCOUNT_WINDOW)
        _audit(db, AuditAction.LOGIN_FAILED, user.id, meta, reason="mfa")
        await db.commit()
        await security_events.emit("mfa_failed", user_id=str(user.id), ip=meta.ip)
        if result.count == 1:
            # Reaching this step required the correct password.
            await deliver(
                emails.security_notice_email(
                    user.email,
                    user.full_name,
                    "Alguém digitou a sua senha corretamente, mas errou o código de verificação "
                    "em duas etapas. Se não foi você, troque sua senha agora.",
                )
            )
        raise InvalidMfaCodeError()
    await redis.delete(key)
    return await _complete_login(db, user, meta, method="password+totp")


async def _verify_second_factor(db: AsyncSession, user: User, code: str, meta: RequestMeta) -> bool:
    assert user.mfa_secret_encrypted is not None
    normalized = "".join(code.split())
    if len(normalized) == 6 and normalized.isdigit():
        return await mfa.verify_totp_once(user.id, decrypt(user.mfa_secret_encrypted), normalized)
    result = await db.execute(
        select(MfaRecoveryCode)
        .where(
            MfaRecoveryCode.user_id == user.id,
            MfaRecoveryCode.code_hash == mfa.hash_recovery_code(code),
            MfaRecoveryCode.used_at.is_(None),
        )
        .with_for_update()
    )
    recovery = result.scalar_one_or_none()
    if recovery is None:
        return False
    recovery.used_at = utcnow()
    _audit(db, AuditAction.MFA_RECOVERY_CODE_USED, user.id, meta)
    return True


async def _complete_login(
    db: AsyncSession, user: User, meta: RequestMeta, *, method: str
) -> LoginResult:
    token = create_session(db, user.id, meta)
    user.last_login_at = utcnow()
    _audit(db, AuditAction.LOGIN_SUCCEEDED, user.id, meta, method=method)
    await db.commit()
    return LoginResult(user=user, session_token=token)


# --------------------------------------------------------------------------- sessions


def create_session(db: AsyncSession, user_id: uuid.UUID, meta: RequestMeta) -> str:
    token = generate_token()
    db.add(
        UserSession(
            user_id=user_id,
            token_hash=hash_token(token),
            ip_address=meta.ip,
            user_agent=(meta.user_agent or "")[:512] or None,
            expires_at=utcnow() + timedelta(days=get_settings().session_ttl_days),
        )
    )
    return token


async def resolve_session(db: AsyncSession, token: str) -> tuple[UserSession, User] | None:
    now = utcnow()
    idle_cutoff = now - timedelta(days=get_settings().session_idle_days)
    result = await db.execute(
        select(UserSession, User)
        .join(User, User.id == UserSession.user_id)
        .where(
            UserSession.token_hash == hash_token(token),
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > now,
            UserSession.last_seen_at > idle_cutoff,
            User.is_active.is_(True),
        )
        .options(selectinload(User.settings))
    )
    row = result.one_or_none()
    if row is None:
        return None
    session, user = row
    if now - session.last_seen_at > SESSION_TOUCH_INTERVAL:
        session.last_seen_at = now
        await db.commit()
    return session, user


async def logout(db: AsyncSession, session: UserSession, meta: RequestMeta) -> None:
    session.revoked_at = utcnow()
    _audit(db, AuditAction.LOGOUT, session.user_id, meta)
    await db.commit()


async def list_sessions(db: AsyncSession, user_id: uuid.UUID) -> list[UserSession]:
    now = utcnow()
    idle_cutoff = now - timedelta(days=get_settings().session_idle_days)
    result = await db.execute(
        select(UserSession)
        .where(
            UserSession.user_id == user_id,
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > now,
            UserSession.last_seen_at > idle_cutoff,
        )
        .order_by(UserSession.last_seen_at.desc())
    )
    return list(result.scalars())


async def revoke_session(
    db: AsyncSession, user_id: uuid.UUID, session_id: uuid.UUID, meta: RequestMeta
) -> None:
    # Filtering by user_id enforces tenant isolation: other users' sessions look nonexistent.
    result = await db.execute(
        update(UserSession)
        .where(
            UserSession.id == session_id,
            UserSession.user_id == user_id,
            UserSession.revoked_at.is_(None),
        )
        .values(revoked_at=utcnow())
    )
    if result.rowcount == 0:  # type: ignore[attr-defined]
        raise NotFoundError("Sessão não encontrada.")
    _audit(db, AuditAction.SESSION_REVOKED, user_id, meta, session_id=str(session_id))
    await db.commit()


async def _revoke_all_sessions(
    db: AsyncSession, user_id: uuid.UUID, *, keep: uuid.UUID | None = None
) -> int:
    stmt = update(UserSession).where(
        UserSession.user_id == user_id, UserSession.revoked_at.is_(None)
    )
    if keep is not None:
        stmt = stmt.where(UserSession.id != keep)
    result = await db.execute(stmt.values(revoked_at=utcnow()))
    return int(result.rowcount)  # type: ignore[attr-defined]


async def revoke_other_sessions(
    db: AsyncSession, user_id: uuid.UUID, current: uuid.UUID, meta: RequestMeta
) -> int:
    count = await _revoke_all_sessions(db, user_id, keep=current)
    _audit(db, AuditAction.SESSION_REVOKED, user_id, meta, scope="others", count=count)
    await db.commit()
    return count


# --------------------------------------------------------------------------- passwords


async def forgot_password(db: AsyncSession, email: str, meta: RequestMeta) -> None:
    await rate_limit.enforce(f"forgot:ip:{meta.ip}", 5, 3600)
    user = await get_user_by_email(db, email)
    if user is None or not user.is_active:
        return
    if not (await rate_limit.hit(f"forgot:email:{email}", 3, 3600)).allowed:
        return
    token = await _issue_token(
        db,
        user.id,
        TokenPurpose.PASSWORD_RESET,
        timedelta(minutes=get_settings().password_reset_ttl_minutes),
    )
    _audit(db, AuditAction.PASSWORD_RESET_REQUESTED, user.id, meta)
    await db.commit()
    await deliver(emails.password_reset_email(user.email, user.full_name, token))


async def reset_password(db: AsyncSession, data: PasswordResetIn, meta: RequestMeta) -> None:
    await rate_limit.enforce(f"reset:ip:{meta.ip}", 10, 3600)
    auth_token = await _consume_token(db, data.token, TokenPurpose.PASSWORD_RESET)
    user = await db.get(User, auth_token.user_id)
    if user is None or not user.is_active:
        raise InvalidTokenError()
    now = utcnow()
    user.password_hash = await asyncio.to_thread(hash_password, data.new_password)
    user.password_changed_at = now
    # The link proves control of the mailbox.
    if user.email_verified_at is None:
        user.email_verified_at = now
    await _revoke_all_sessions(db, user.id)
    _audit(db, AuditAction.PASSWORD_RESET, user.id, meta)
    await db.commit()
    await rate_limit.reset(f"login:fail:{user.email}")
    await deliver(
        emails.security_notice_email(
            user.email,
            user.full_name,
            "Sua senha foi redefinida e todas as sessões foram encerradas.",
        )
    )


async def _require_password(user: User, password: str) -> None:
    await rate_limit.enforce(f"reauth:{user.id}", 5, 900)
    if not await asyncio.to_thread(verify_password, user.password_hash, password):
        raise InvalidCredentialsError("Senha atual incorreta.")


async def change_password(
    db: AsyncSession,
    user: User,
    session: UserSession,
    current_password: str,
    new_password: str,
    meta: RequestMeta,
) -> None:
    await _require_password(user, current_password)
    user.password_hash = await asyncio.to_thread(hash_password, new_password)
    user.password_changed_at = utcnow()
    await _revoke_all_sessions(db, user.id, keep=session.id)
    _audit(db, AuditAction.PASSWORD_CHANGED, user.id, meta)
    await db.commit()
    await deliver(
        emails.security_notice_email(
            user.email,
            user.full_name,
            "Sua senha foi alterada. As demais sessões ativas foram encerradas.",
        )
    )


# --------------------------------------------------------------------------- 2FA


async def start_mfa_setup(user: User, password: str) -> tuple[str, str]:
    if user.mfa_enabled:
        raise ConflictError("A autenticação em dois fatores já está ativa.")
    # A session alone is not enough: with a stolen one, an attacker could enrol their own
    # authenticator and lock the owner out of the next sign-in.
    await _require_password(user, password)
    secret = mfa.new_secret()
    await get_redis().set(f"mfa_setup:{user.id}", encrypt(secret), ex=MFA_SETUP_TTL)
    return secret, mfa.provisioning_uri(secret, user.email)


async def _store_recovery_codes(db: AsyncSession, user_id: uuid.UUID) -> list[str]:
    await db.execute(delete(MfaRecoveryCode).where(MfaRecoveryCode.user_id == user_id))
    codes = mfa.generate_recovery_codes()
    db.add_all(MfaRecoveryCode(user_id=user_id, code_hash=mfa.hash_recovery_code(c)) for c in codes)
    return codes


async def enable_mfa(db: AsyncSession, user: User, code: str, meta: RequestMeta) -> list[str]:
    if user.mfa_enabled:
        raise ConflictError("A autenticação em dois fatores já está ativa.")
    await rate_limit.enforce(f"mfa_enable:{user.id}", 10, 900)
    redis = get_redis()
    encrypted = await redis.get(f"mfa_setup:{user.id}")
    if encrypted is None:
        raise AppError("A configuração expirou. Gere um novo QR code.", code="mfa_setup_expired")
    secret = decrypt(encrypted)
    if not await mfa.verify_totp_once(user.id, secret, code):
        raise InvalidMfaCodeError()
    user.mfa_secret_encrypted = encrypt(secret)
    user.mfa_enabled_at = utcnow()
    codes = await _store_recovery_codes(db, user.id)
    _audit(db, AuditAction.MFA_ENABLED, user.id, meta)
    await db.commit()
    await redis.delete(f"mfa_setup:{user.id}")
    await deliver(
        emails.security_notice_email(
            user.email, user.full_name, "A autenticação em dois fatores foi ativada na sua conta."
        )
    )
    return codes


async def _require_second_factor(
    db: AsyncSession, user: User, code: str, meta: RequestMeta
) -> None:
    await rate_limit.enforce(f"mfa_verify:{user.id}", 10, 900)
    if not await _verify_second_factor(db, user, code, meta):
        raise InvalidMfaCodeError()


async def disable_mfa(
    db: AsyncSession, user: User, password: str, code: str, meta: RequestMeta
) -> None:
    if not user.mfa_enabled:
        raise ConflictError("A autenticação em dois fatores não está ativa.")
    await _require_password(user, password)
    await _require_second_factor(db, user, code, meta)
    user.mfa_secret_encrypted = None
    user.mfa_enabled_at = None
    await db.execute(delete(MfaRecoveryCode).where(MfaRecoveryCode.user_id == user.id))
    _audit(db, AuditAction.MFA_DISABLED, user.id, meta)
    await db.commit()
    await deliver(
        emails.security_notice_email(
            user.email,
            user.full_name,
            "A autenticação em dois fatores foi desativada na sua conta.",
        )
    )


async def regenerate_recovery_codes(
    db: AsyncSession, user: User, code: str, meta: RequestMeta
) -> list[str]:
    if not user.mfa_enabled:
        raise ConflictError("A autenticação em dois fatores não está ativa.")
    await _require_second_factor(db, user, code, meta)
    codes = await _store_recovery_codes(db, user.id)
    _audit(db, AuditAction.MFA_RECOVERY_CODES_REGENERATED, user.id, meta)
    await db.commit()
    return codes


# --------------------------------------------------------------------------- maintenance


async def purge_expired(db: AsyncSession) -> None:
    """Drop expired sessions/tokens (retention: 30 days after expiry, for audit context)."""
    cutoff = utcnow() - timedelta(days=30)
    await db.execute(delete(UserSession).where(UserSession.expires_at < cutoff))
    await db.execute(delete(AuthToken).where(AuthToken.expires_at < cutoff))
    await db.commit()
