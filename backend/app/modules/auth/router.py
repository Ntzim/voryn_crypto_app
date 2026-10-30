import uuid

from fastapi import APIRouter, Request, Response, status

from app.core.config import get_settings
from app.core.security import generate_token
from app.modules.auth import service
from app.modules.auth.deps import CurrentAuth, DbSession, Meta
from app.modules.auth.schemas import (
    CsrfOut,
    EmailIn,
    LoginIn,
    LoginOut,
    MessageOut,
    MfaCodeIn,
    MfaDisableIn,
    MfaEnableOut,
    MfaLoginIn,
    MfaSetupOut,
    PasswordResetIn,
    RegisterIn,
    TokenIn,
)
from app.modules.users.schemas import PasswordChangeIn, SessionOut, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])
security_router = APIRouter(prefix="/me", tags=["account-security"])

GENERIC_EMAIL_SENT = "Se o e-mail estiver apto, você receberá as instruções em instantes."


def _set_session_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        settings.session_cookie_name,
        token,
        max_age=settings.session_ttl_days * 86400,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(
        settings.session_cookie_name,
        path="/",
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )


@router.get("/csrf")
async def csrf(request: Request, response: Response) -> CsrfOut:
    """Issue (or return) the double-submit CSRF token. Readable by JS on purpose."""
    settings = get_settings()
    token = request.cookies.get(settings.csrf_cookie_name) or generate_token(24)
    response.set_cookie(
        settings.csrf_cookie_name,
        token,
        max_age=settings.session_ttl_days * 86400,
        httponly=False,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    return CsrfOut(csrf_token=token)


@router.post("/register", status_code=status.HTTP_202_ACCEPTED)
async def register(data: RegisterIn, db: DbSession, meta: Meta) -> MessageOut:
    await service.register(db, data, meta)
    return MessageOut(message="Conta criada. Enviamos um link de confirmação para o seu e-mail.")


@router.post("/email/verify")
async def verify_email(data: TokenIn, db: DbSession, meta: Meta) -> MessageOut:
    await service.verify_email(db, data.token, meta)
    return MessageOut(message="E-mail confirmado. Você já pode entrar.")


@router.post("/email/resend", status_code=status.HTTP_202_ACCEPTED)
async def resend_verification(data: EmailIn, db: DbSession, meta: Meta) -> MessageOut:
    await service.resend_verification(db, data.email, meta)
    return MessageOut(message=GENERIC_EMAIL_SENT)


@router.post("/login")
async def login(data: LoginIn, response: Response, db: DbSession, meta: Meta) -> LoginOut:
    result = await service.login(db, data, meta)
    if result.mfa_token:
        return LoginOut(status="mfa_required", mfa_token=result.mfa_token)
    assert result.session_token and result.user
    _set_session_cookie(response, result.session_token)
    return LoginOut(status="authenticated", user=UserOut.model_validate(result.user))


@router.post("/login/mfa")
async def login_mfa(data: MfaLoginIn, response: Response, db: DbSession, meta: Meta) -> LoginOut:
    result = await service.login_with_mfa(db, data.mfa_token, data.code, meta)
    assert result.session_token and result.user
    _set_session_cookie(response, result.session_token)
    return LoginOut(status="authenticated", user=UserOut.model_validate(result.user))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(auth: CurrentAuth, response: Response, db: DbSession, meta: Meta) -> None:
    await service.logout(db, auth.session, meta)
    _clear_session_cookie(response)


@router.post("/password/forgot", status_code=status.HTTP_202_ACCEPTED)
async def forgot_password(data: EmailIn, db: DbSession, meta: Meta) -> MessageOut:
    await service.forgot_password(db, data.email, meta)
    return MessageOut(message=GENERIC_EMAIL_SENT)


@router.post("/password/reset")
async def reset_password(data: PasswordResetIn, db: DbSession, meta: Meta) -> MessageOut:
    await service.reset_password(db, data, meta)
    return MessageOut(message="Senha redefinida. Entre com sua nova senha.")


# --------------------------------------------------------------------------- /me security


@security_router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    data: PasswordChangeIn, auth: CurrentAuth, db: DbSession, meta: Meta
) -> None:
    await service.change_password(
        db, auth.user, auth.session, data.current_password, data.new_password, meta
    )


@security_router.get("/sessions")
async def list_sessions(auth: CurrentAuth, db: DbSession) -> list[SessionOut]:
    sessions = await service.list_sessions(db, auth.user.id)
    return [
        SessionOut(
            id=s.id,
            ip_address=s.ip_address,
            user_agent=s.user_agent,
            created_at=s.created_at,
            last_seen_at=s.last_seen_at,
            expires_at=s.expires_at,
            current=s.id == auth.session.id,
        )
        for s in sessions
    ]


@security_router.post("/sessions/revoke-others")
async def revoke_other_sessions(auth: CurrentAuth, db: DbSession, meta: Meta) -> MessageOut:
    count = await service.revoke_other_sessions(db, auth.user.id, auth.session.id, meta)
    return MessageOut(message=f"{count} sessão(ões) encerrada(s).")


@security_router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_session(
    session_id: uuid.UUID, auth: CurrentAuth, db: DbSession, meta: Meta
) -> None:
    await service.revoke_session(db, auth.user.id, session_id, meta)


@security_router.post("/mfa/setup")
async def mfa_setup(auth: CurrentAuth) -> MfaSetupOut:
    secret, uri = await service.start_mfa_setup(auth.user)
    return MfaSetupOut(secret=secret, otpauth_uri=uri)


@security_router.post("/mfa/enable")
async def mfa_enable(data: MfaCodeIn, auth: CurrentAuth, db: DbSession, meta: Meta) -> MfaEnableOut:
    codes = await service.enable_mfa(db, auth.user, data.code, meta)
    return MfaEnableOut(recovery_codes=codes)


@security_router.post("/mfa/disable", status_code=status.HTTP_204_NO_CONTENT)
async def mfa_disable(data: MfaDisableIn, auth: CurrentAuth, db: DbSession, meta: Meta) -> None:
    await service.disable_mfa(db, auth.user, data.password, data.code, meta)


@security_router.post("/mfa/recovery-codes")
async def mfa_recovery_codes(
    data: MfaCodeIn, auth: CurrentAuth, db: DbSession, meta: Meta
) -> MfaEnableOut:
    codes = await service.regenerate_recovery_codes(db, auth.user, data.code, meta)
    return MfaEnableOut(recovery_codes=codes)
