"""Production configuration guards and the HTTPS e-mail backend used on Railway."""

import json

import httpx
import pytest
from cryptography.fernet import Fernet

from app.core import email
from app.core.config import Settings, get_settings

PRODUCTION = {
    "environment": "production",
    "secret_key": "x" * 48,
    "encryption_keys": Fernet.generate_key().decode(),
    "frontend_url": "voryn.up.railway.app",
    "email_backend": "resend",
    "resend_api_key": "re_test",
    "trust_proxy_headers": True,
    # The test environment relaxes these; production values are set explicitly.
    "cookie_secure": True,
    "rate_limit_scale": 1,
}


def test_complete_production_settings_pass() -> None:
    settings = Settings(**PRODUCTION)  # type: ignore[arg-type]
    settings.validate_for_runtime()
    assert settings.frontend_url == "https://voryn.up.railway.app"  # Railway domain has no scheme


@pytest.mark.parametrize(
    ("override", "problem"),
    [
        ({"secret_key": "short"}, "SECRET_KEY"),
        ({"encryption_keys": ""}, "ENCRYPTION_KEYS"),
        ({"email_backend": "console"}, "EMAIL_BACKEND"),
        ({"resend_api_key": ""}, "RESEND_API_KEY"),
        ({"email_backend": "smtp", "smtp_host": "localhost"}, "SMTP_HOST"),
        ({"frontend_url": "http://localhost:3000"}, "FRONTEND_URL"),
        ({"trust_proxy_headers": False}, "TRUST_PROXY_HEADERS"),
        ({"rate_limit_scale": 20}, "RATE_LIMIT_SCALE"),
        ({"cookie_secure": False}, "COOKIE_SECURE"),
    ],
)
def test_insecure_production_settings_refuse_to_start(
    override: dict[str, object], problem: str
) -> None:
    settings = Settings(**{**PRODUCTION, **override})  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match=problem):
        settings.validate_for_runtime()


def test_railway_database_url_gets_the_async_driver() -> None:
    settings = Settings(database_url="postgresql://u:p@postgres.railway.internal:5432/railway")
    assert settings.database_url.startswith("postgresql+asyncpg://")


async def test_resend_backend_posts_the_message(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"id": "email_1"})

    monkeypatch.setenv("RESEND_API_KEY", "re_secret")
    monkeypatch.setenv("EMAIL_FROM", "Voryn <no-reply@voryn.app>")
    get_settings.cache_clear()
    try:
        backend = email.ResendBackend(transport=httpx.MockTransport(handler))
        await backend.send(
            email.EmailMessage(to="ana@example.com", subject="Oi", text="t", html="<p>t</p>")
        )
    finally:
        get_settings.cache_clear()
    (request,) = seen
    assert str(request.url) == "https://api.resend.com/emails"
    assert request.headers["Authorization"] == "Bearer re_secret"
    body = json.loads(request.content)
    assert body == {
        "from": "Voryn <no-reply@voryn.app>",
        "to": ["ana@example.com"],
        "subject": "Oi",
        "text": "t",
        "html": "<p>t</p>",
    }


async def test_resend_errors_raise_so_the_worker_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RESEND_API_KEY", "re_secret")
    get_settings.cache_clear()
    try:
        backend = email.ResendBackend(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(422, json={"message": "domain not verified"})
            )
        )
        email.set_email_backend(backend)
        message = email.EmailMessage(to="ana@example.com", subject="Oi", text="t")
        await email.send_email(message)  # request path: swallowed
        with pytest.raises(RuntimeError, match="domain not verified"):
            await email.send_email(message, raise_errors=True)  # worker path: retried
    finally:
        email.set_email_backend(None)
        get_settings.cache_clear()
