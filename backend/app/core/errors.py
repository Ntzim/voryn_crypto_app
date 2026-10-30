"""Consistent error envelope: {"error": {"code", "message", "details"}, "request_id"}."""

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core import security_events
from app.core.logging import get_logger

logger = get_logger(__name__)


class AppError(Exception):
    status_code: int = status.HTTP_400_BAD_REQUEST
    code: str = "bad_request"
    message: str = "Requisição inválida."

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        status_code: int | None = None,
        details: Any = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.message = message or self.message
        self.code = code or self.code
        self.status_code = status_code or self.status_code
        self.details = details
        self.headers = headers
        super().__init__(self.message)


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"
    message = "Recurso não encontrado."


class UnauthorizedError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "unauthorized"
    message = "Autenticação necessária."


class ForbiddenError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "forbidden"
    message = "Acesso negado."


class ConflictError(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = "conflict"
    message = "A operação conflita com o estado atual."


class RateLimitedError(AppError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "rate_limited"
    message = "Muitas tentativas. Aguarde antes de tentar novamente."

    def __init__(self, retry_after: int, message: str | None = None) -> None:
        super().__init__(
            message,
            details={"retry_after": retry_after},
            headers={"Retry-After": str(retry_after)},
        )


def error_body(request: Request, code: str, message: str, details: Any = None) -> dict[str, Any]:
    return {
        "error": {"code": code, "message": message, "details": details},
        "request_id": getattr(request.state, "request_id", None),
    }


def _translate(err: Any) -> str:
    """User-facing pt-BR messages for the validation errors our forms can trigger."""
    kind: str = err.get("type", "")
    ctx: dict[str, Any] = err.get("ctx") or {}
    message: str = err.get("msg", "")
    if kind == "missing":
        return "Campo obrigatório."
    if kind == "string_too_short":
        return f"Deve ter pelo menos {ctx.get('min_length')} caracteres."
    if kind == "string_too_long":
        return f"Deve ter no máximo {ctx.get('max_length')} caracteres."
    if kind == "value_error" and "email" in message.lower():
        return "Informe um e-mail válido."
    if kind == "value_error":
        return message.removeprefix("Value error, ")
    if kind in {"literal_error", "enum"}:
        return "Valor não permitido."
    return "Valor inválido."


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        if exc.status_code == 429:
            await security_events.emit("rate_limited", path=request.url.path, code=exc.code)
        return JSONResponse(
            error_body(request, exc.code, exc.message, exc.details),
            status_code=exc.status_code,
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"field": ".".join(str(p) for p in err["loc"][1:]), "message": _translate(err)}
            for err in exc.errors()
        ]
        return JSONResponse(
            error_body(request, "validation_error", "Dados inválidos.", details),
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
        return JSONResponse(
            error_body(request, code, str(exc.detail)),
            status_code=exc.status_code,
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_error", path=request.url.path)
        await security_events.emit("server_error", path=request.url.path)
        return JSONResponse(
            error_body(request, "internal_error", "Erro interno. Tente novamente mais tarde."),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
