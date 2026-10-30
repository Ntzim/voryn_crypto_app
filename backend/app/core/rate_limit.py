"""Redis fixed-window rate limiting.

Fixed windows are coarse but cheap and predictable; good enough for abuse protection
on auth endpoints and a global per-IP ceiling.
"""

from dataclasses import dataclass

from app.core.config import get_settings
from app.core.errors import RateLimitedError
from app.core.redis import get_redis


@dataclass(frozen=True, slots=True)
class RateLimitResult:
    allowed: bool
    count: int
    retry_after: int


async def hit(key: str, limit: int, window_seconds: int) -> RateLimitResult:
    redis = get_redis()
    full_key = f"rl:{key}"
    async with redis.pipeline(transaction=True) as pipe:
        pipe.incr(full_key)
        pipe.expire(full_key, window_seconds, nx=True)
        pipe.ttl(full_key)
        count, _, ttl = await pipe.execute()
    retry_after = max(int(ttl), 1)
    limit *= get_settings().rate_limit_scale
    return RateLimitResult(allowed=int(count) <= limit, count=int(count), retry_after=retry_after)


async def enforce(key: str, limit: int, window_seconds: int) -> None:
    result = await hit(key, limit, window_seconds)
    if not result.allowed:
        raise RateLimitedError(result.retry_after)


async def peek(key: str) -> tuple[int, int]:
    """Current count and remaining TTL without incrementing."""
    redis = get_redis()
    full_key = f"rl:{key}"
    async with redis.pipeline(transaction=False) as pipe:
        pipe.get(full_key)
        pipe.ttl(full_key)
        raw, ttl = await pipe.execute()
    return int(raw or 0), max(int(ttl), 1)


async def reset(key: str) -> None:
    await get_redis().delete(f"rl:{key}")
