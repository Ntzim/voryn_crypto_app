"""HTTP middleware: request id + access log, security headers, CSRF, global rate limit."""

import time
import uuid
from contextvars import ContextVar

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core import rate_limit, security_events
from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.security import constant_time_equals

logger = get_logger("voryn.http")

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
CSRF_HEADER = "x-csrf-token"
GLOBAL_LIMIT_PER_MINUTE = 300


#: client address of the request being served, for code without the Request at hand
_current_client_ip: ContextVar[str | None] = ContextVar("client_ip", default=None)


def current_client_ip() -> str | None:
    return _current_client_ip.get()


def client_ip(request: Request) -> str:
    if get_settings().trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            # Right-most entry is the one appended by our trusted edge; left entries are
            # client-controlled and trivially spoofed.
            return forwarded.split(",")[-1].strip()[:45]
    return request.client.host if request.client else "unknown"


def _error(request: Request, status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        {
            "error": {"code": code, "message": message, "details": None},
            "request_id": getattr(request.state, "request_id", None),
        },
        status_code=status,
    )


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        incoming = request.headers.get("x-request-id", "")
        request_id = incoming if 0 < len(incoming) <= 64 else uuid.uuid4().hex
        request.state.request_id = request_id
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        _current_client_ip.set(client_ip(request))
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - start) * 1000, 1)
        response.headers["X-Request-ID"] = request_id
        if not request.url.path.startswith("/health"):
            logger.info(
                "http_request",
                method=request.method,
                path=request.url.path,
                status=response.status_code,
                duration_ms=duration_ms,
            )
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Cache-Control", "no-store")
        if get_settings().is_production:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=63072000; includeSubDomains"
            )
        return response


class CSRFMiddleware(BaseHTTPMiddleware):
    """Double-submit cookie: unsafe requests must echo the CSRF cookie in X-CSRF-Token.

    Combined with SameSite=Lax session cookies this blocks cross-site form posts and
    fetches, including login CSRF.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method in SAFE_METHODS or not request.url.path.startswith("/api/"):
            return await call_next(request)
        cookie = request.cookies.get(get_settings().csrf_cookie_name, "")
        header = request.headers.get(CSRF_HEADER, "")
        if not cookie or not header or not constant_time_equals(cookie, header):
            return _error(request, 403, "csrf_failed", "Falha na verificação CSRF.")
        return await call_next(request)


class GlobalRateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if not request.url.path.startswith("/api/"):
            return await call_next(request)
        result = await rate_limit.hit(f"global:{client_ip(request)}", GLOBAL_LIMIT_PER_MINUTE, 60)
        if not result.allowed:
            await security_events.emit("rate_limited", path=request.url.path, code="global")
            response = _error(request, 429, "rate_limited", "Limite de requisições excedido.")
            response.headers["Retry-After"] = str(result.retry_after)
            return response
        return await call_next(request)
