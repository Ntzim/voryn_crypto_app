"""Notification delivery channels.

In-app delivery *is* the stored notification; other channels are sent on top of it.
New channels (push, Telegram, mobile) implement `Channel` and are added to `CHANNELS`
without touching alert evaluation.
"""

from typing import Protocol

from app.core import rate_limit
from app.core.config import get_settings
from app.core.email import EmailMessage, deliver
from app.modules.alerts.models import Alert, Notification
from app.modules.users.models import User

#: Per-user ceilings, protecting inboxes from alert storms.
EMAIL_PER_HOUR = 10


class Channel(Protocol):
    name: str

    def wants(self, alert: Alert | None) -> bool: ...

    async def send(self, user: User, notification: Notification) -> bool: ...


class EmailChannel:
    name = "email"

    def wants(self, alert: Alert | None) -> bool:
        return alert is not None and alert.notify_email

    async def send(self, user: User, notification: Notification) -> bool:
        allowed = (await rate_limit.hit(f"notify:email:{user.id}", EMAIL_PER_HOUR, 3600)).allowed
        if not allowed:
            return False
        link = f"{get_settings().frontend_url.rstrip('/')}/alertas"
        await deliver(
            EmailMessage(
                to=user.email,
                subject=f"Voryn · {notification.title}",
                text=(
                    f"{notification.body}\n\nGerencie seus alertas: {link}\n\n"
                    "Alertas são informativos e não constituem recomendação de investimento."
                ),
            )
        )
        return True


CHANNELS: list[Channel] = [EmailChannel()]
