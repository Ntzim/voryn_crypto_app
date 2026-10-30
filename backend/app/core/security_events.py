"""Security monitoring without an external service.

`emit` writes one structured `security_event` log line (searchable in the Railway logs)
and counts the event in a Redis bucket per 5-minute window. The `security.check` beat
task compares the last complete window with THRESHOLDS and raises a `security_alert`
(error-level log, plus an e-mail to SECURITY_ALERT_EMAIL when set) once per kind per hour.
"""

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

from app.core.logging import get_logger
from app.core.redis import get_redis

logger = get_logger("voryn.security")

EventKind = Literal[
    "login_failed",
    "mfa_failed",
    "session_invalid",
    "access_denied",
    "rate_limited",
    "exchange_sync_failed",
    "signal_blocked",
    "processing_failed",
    "server_error",
]
WINDOW_SECONDS = 300
#: events per 5-minute window above which an alert is raised (sized for the current
#: traffic; a single user mistyping a password stays far below)
THRESHOLDS: dict[str, int] = {
    "login_failed": 50,
    "mfa_failed": 10,
    "session_invalid": 200,
    "access_denied": 10,
    "rate_limited": 100,
    "exchange_sync_failed": 20,
    "signal_blocked": 50,
    "processing_failed": 10,
    "server_error": 10,
}
ALERT_COOLDOWN_SECONDS = 3600


def _bucket(at: float | None = None) -> int:
    return int((at if at is not None else time.time()) // WINDOW_SECONDS)


async def emit(kind: EventKind, **fields: Any) -> None:
    """Record a security event. Never pass secrets, tokens or full credentials."""
    logger.warning("security_event", kind=kind, **fields)
    key = f"secev:{kind}:{_bucket()}"
    try:
        async with get_redis().pipeline(transaction=False) as pipe:
            pipe.incr(key)
            pipe.expire(key, WINDOW_SECONDS * 3)
            await pipe.execute()
    except Exception as exc:  # monitoring must never break the request it observes
        logger.warning("security_event_count_failed", kind=kind, error=type(exc).__name__)


async def counts(bucket: int) -> dict[str, int]:
    redis = get_redis()
    values = await redis.mget([f"secev:{kind}:{bucket}" for kind in THRESHOLDS])
    return {kind: int(v or 0) for kind, v in zip(THRESHOLDS, values, strict=True)}


@dataclass(frozen=True, slots=True)
class Alert:
    kind: str
    count: int
    threshold: int


async def check(
    notify: Callable[[list[Alert]], Awaitable[None]] | None = None, *, at: float | None = None
) -> list[Alert]:
    """Alert on the last complete window. Each kind alerts at most once per hour."""
    window = await counts(_bucket(at) - 1)
    redis = get_redis()
    alerts = []
    for kind, count in window.items():
        if count <= THRESHOLDS[kind]:
            continue
        first = await redis.set(f"secalert:{kind}", "1", nx=True, ex=ALERT_COOLDOWN_SECONDS)
        if first:
            alerts.append(Alert(kind, count, THRESHOLDS[kind]))
    for alert in alerts:
        logger.error(
            "security_alert",
            kind=alert.kind,
            count=alert.count,
            threshold=alert.threshold,
            window_seconds=WINDOW_SECONDS,
        )
    if alerts and notify is not None:
        await notify(alerts)
    return alerts
