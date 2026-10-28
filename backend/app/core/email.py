"""Outbound e-mail with pluggable backends (smtp, console, memory)."""

import asyncio
import smtplib
from dataclasses import asdict, dataclass
from email.message import EmailMessage as MimeMessage
from typing import Protocol

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
            "console": ConsoleBackend,
            "memory": MemoryBackend,
        }
        _backend = backends[get_settings().email_backend]()
    return _backend


def set_email_backend(backend: EmailBackend | None) -> None:
    global _backend
    _backend = backend


async def send_email(message: EmailMessage) -> None:
    """Send without failing the caller: auth flows must not leak delivery errors to clients."""
    try:
        await get_email_backend().send(message)
    except Exception:
        logger.exception("email_send_failed", subject=message.subject)


async def deliver(message: EmailMessage) -> None:
    """Entry point for application code: queue (default) or send inline."""
    if get_settings().email_delivery == "inline":
        await send_email(message)
        return
    from app.worker import send_email_task

    await asyncio.to_thread(send_email_task.delay, asdict(message))
