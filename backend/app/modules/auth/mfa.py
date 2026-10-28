"""TOTP (RFC 6238) and recovery codes."""

import hmac
import secrets
import time
import uuid

import pyotp

from app.core.redis import get_redis
from app.core.security import hash_token

ISSUER = "Voryn"
RECOVERY_CODE_COUNT = 10
_RECOVERY_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # no 0/o/1/l/i ambiguity
_TOTP_STEP = 30


def new_secret() -> str:
    return pyotp.random_base32()


def provisioning_uri(secret: str, email: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=ISSUER)


def _normalize_code(code: str) -> str:
    return "".join(ch for ch in code if not ch.isspace())


def matching_timecode(secret: str, code: str, *, at: float | None = None) -> int | None:
    """Return the matched TOTP counter (±1 step for clock drift) or None."""
    code = _normalize_code(code)
    if len(code) != 6 or not code.isdigit():
        return None
    totp = pyotp.TOTP(secret)
    now = int(at if at is not None else time.time())
    current = now // _TOTP_STEP
    for counter in (current - 1, current, current + 1):
        if hmac.compare_digest(totp.generate_otp(counter), code):
            return counter
    return None


async def verify_totp_once(user_id: uuid.UUID, secret: str, code: str) -> bool:
    """Verify a TOTP code and reject replays of the same time-step."""
    counter = matching_timecode(secret, code)
    if counter is None:
        return False
    first_use = await get_redis().set(
        f"totp_used:{user_id}:{counter}", "1", nx=True, ex=_TOTP_STEP * 4
    )
    return bool(first_use)


def normalize_recovery_code(code: str) -> str:
    return _normalize_code(code).replace("-", "").lower()


def generate_recovery_codes() -> list[str]:
    codes = []
    for _ in range(RECOVERY_CODE_COUNT):
        raw = "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(10))
        codes.append(f"{raw[:5]}-{raw[5:]}")
    return codes


def hash_recovery_code(code: str) -> str:
    return hash_token("recovery:" + normalize_recovery_code(code))
