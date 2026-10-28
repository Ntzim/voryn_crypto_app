"""Celery worker + beat schedule for background jobs.

Tasks are thin sync wrappers around async use-cases; each run gets its own event loop and
a NullPool engine, so no connection is shared across loops.
"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from celery import Celery
from celery.signals import worker_ready
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import models as _models  # noqa: F401  (registers ORM mappers)
from app.core import redis as redis_module
from app.core.config import get_settings
from app.core.db import build_engine
from app.core.email import EmailMessage, send_email
from app.core.logging import configure_logging, get_logger
from app.modules.auth.service import purge_expired
from app.modules.market_data import service as market
from app.modules.market_data.providers.base import ProviderError
from app.modules.market_data.providers.coingecko import CoinGeckoProvider

settings = get_settings()
configure_logging()
logger = get_logger("voryn.worker")

celery_app = Celery("voryn", broker=settings.redis_url, backend=None)
celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_default_queue="voryn",
    # Keep our structlog handlers instead of Celery's formatter wrapping them.
    worker_hijack_root_logger=False,
    timezone="UTC",
    beat_schedule={
        "sync-markets": {
            "task": "market.sync_markets",
            "schedule": float(settings.market_sync_interval_seconds),
        },
        "sync-fx": {"task": "market.sync_fx", "schedule": float(settings.fx_sync_interval_seconds)},
        "prune-market-history": {"task": "market.prune_history", "schedule": 6 * 3600.0},
        "purge-auth": {"task": "auth.purge_expired", "schedule": 24 * 3600.0},
    },
)


def _run[T](job: Callable[[AsyncSession], Awaitable[T]]) -> T:
    async def runner() -> T:
        engine = build_engine(null_pool=True)
        redis_module.set_redis(None)  # fresh client bound to this loop
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                return await job(session)
        finally:
            await engine.dispose()
            await redis_module.close_redis()

    return asyncio.run(runner())


@celery_app.task(name="email.send", autoretry_for=(Exception,), retry_backoff=True, max_retries=5)
def send_email_task(message: dict[str, Any]) -> None:
    asyncio.run(send_email(EmailMessage(**message)))


async def _sync_markets(db: AsyncSession) -> int:
    provider = CoinGeckoProvider()
    try:
        return await market.sync_markets(db, provider)
    except ProviderError as exc:
        logger.error("market_sync_failed", error=str(exc))
        await market.record_sync_failure(str(exc))
        return 0
    finally:
        await provider.aclose()


async def _sync_fx(db: AsyncSession) -> str | None:
    provider = CoinGeckoProvider()
    try:
        return str(await market.sync_fx(db, provider))
    except ProviderError as exc:
        logger.error("fx_sync_failed", error=str(exc))
        return None
    finally:
        await provider.aclose()


@celery_app.task(name="market.sync_markets")
def sync_markets_task() -> int:
    return _run(_sync_markets)


@celery_app.task(name="market.sync_fx")
def sync_fx_task() -> str | None:
    return _run(_sync_fx)


@celery_app.task(name="market.prune_history")
def prune_history_task() -> int:
    return _run(market.prune_history)


@celery_app.task(name="auth.purge_expired")
def purge_expired_task() -> None:
    _run(purge_expired)


@worker_ready.connect
def _bootstrap(**_: Any) -> None:
    # Populate data right away instead of waiting for the first beat tick.
    sync_fx_task.delay()
    sync_markets_task.delay()
