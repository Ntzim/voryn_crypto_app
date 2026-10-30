from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security_events
from app.core.config import get_settings
from app.core.db import get_db
from app.core.errors import UnauthorizedError
from app.core.middleware import client_ip
from app.modules.auth.models import UserSession
from app.modules.auth.service import RequestMeta, resolve_session
from app.modules.users.models import User

DbSession = Annotated[AsyncSession, Depends(get_db)]


@dataclass(frozen=True, slots=True)
class AuthContext:
    user: User
    session: UserSession


def get_request_meta(request: Request) -> RequestMeta:
    return RequestMeta(ip=client_ip(request), user_agent=request.headers.get("user-agent"))


async def get_auth_context(request: Request, db: DbSession) -> AuthContext:
    token = request.cookies.get(get_settings().session_cookie_name)
    if not token:
        raise UnauthorizedError()
    resolved = await resolve_session(db, token)
    if resolved is None:
        await security_events.emit("session_invalid", ip=client_ip(request))
        raise UnauthorizedError("Sua sessão expirou. Entre novamente.", code="session_expired")
    session, user = resolved
    return AuthContext(user=user, session=session)


Meta = Annotated[RequestMeta, Depends(get_request_meta)]
CurrentAuth = Annotated[AuthContext, Depends(get_auth_context)]
