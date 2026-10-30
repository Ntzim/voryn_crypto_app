"""Outbound e-mail with pluggable backends (smtp, resend, console, memory)."""

import asyncio
import smtplib
from dataclasses import asdict, dataclass
from email.message import EmailMessage as MimeMessage
from typing import Protocol

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class EmailMessage:
    to: str
    subject: str
    text: str
    html: str | None = None


class EmailBackend(Protocol):
    async def send(self, message: EmailMessage) -> None: ...


class SMTPBackend:
    def _send_sync(self, message: EmailMessage) -> None:
        settings = get_settings()
        mime = MimeMessage()
        mime["From"] = settings.email_from
        mime["To"] = message.to
        mime["Subject"] = message.subject
        mime.set_content(message.text)
        if message.html:
            mime.add_alternative(message.html, subtype="html")
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
            if settings.smtp_starttls:
                smtp.starttls()
            if settings.smtp_username and settings.smtp_password:
                smtp.login(settings.smtp_username, settings.smtp_password.get_secret_value())
            smtp.send_message(mime)

    async def send(self, message: EmailMessage) -> None:
        await asyncio.to_thread(self._send_sync, message)


class ResendBackend:
    """Resend transactional e-mail over HTTPS (https://resend.com/docs/api-reference)."""

    URL = "https://api.resend.com/emails"

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    async def send(self, message: EmailMessage) -> None:
        settings = get_settings()
        if settings.resend_api_key is None:
            raise RuntimeError("RESEND_API_KEY is not configured")
        payload: dict[str, object] = {
            "from": settings.email_from,
            "to": [message.to],
            "subject": message.subject,
            "text": message.text,
        }
        if message.html:
            payload["html"] = message.html
        async with httpx.AsyncClient(timeout=15, transport=self._transport) as client:
            response = await client.post(
                self.URL,
                json=payload,
                headers={"Authorization": f"Bearer {settings.resend_api_key.get_secret_value()}"},
            )
        if response.status_code >= 400:
            # The body explains the problem (domain not verified, invalid from…); no secrets.
            raise RuntimeError(
                f"Resend rejected the e-mail: {response.status_code} {response.text[:300]}"
            )


class ConsoleBackend:
    async def send(self, message: EmailMessage) -> None:
        logger.info("email_console", to=message.to, subject=message.subject, body=message.text)


class MemoryBackend:
    """Collects messages in-process; used by the test-suite."""

    def __init__(self) -> None:
        self.outbox: list[EmailMessage] = []

    async def send(self, message: EmailMessage) -> None:
        self.outbox.append(message)


_backend: EmailBackend | None = None


def get_email_backend() -> EmailBackend:
    global _backend
    if _backend is None:
        backends: dict[str, type[EmailBackend]] = {
            "smtp": SMTPBackend,
            "resend": ResendBackend,
            "console": ConsoleBackend,
            "memory": MemoryBackend,
        }
        _backend = backends[get_settings().email_backend]()
    return _backend


def set_email_backend(backend: EmailBackend | None) -> None:
    global _backend
    _backend = backend


async def send_email(message: EmailMessage, *, raise_errors: bool = False) -> None:
    """Send without failing the caller: auth flows must not leak delivery errors to clients.

    The worker passes raise_errors=True so a failed delivery is retried with backoff.
    """
    try:
        await get_email_backend().send(message)
    except Exception:
        logger.exception("email_send_failed", subject=message.subject)
        if raise_errors:
            raise


async def deliver(message: EmailMessage) -> None:
    """Entry point for application code: queue (default) or send inline."""
    if get_settings().email_delivery == "inline":
        await send_email(message)
        return
    from app.worker import send_email_task

    await asyncio.to_thread(send_email_task.delay, asdict(message))
