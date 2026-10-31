"""Exchange markets (B3 now, US later): catalogue and delayed quote sync, market search.

Exchange instruments share the `cryptocurrencies` table with crypto (told apart by
`market`), but have their own sync, freshness rules and labels:

- quotes are stored in the instrument's own currency (BRL for B3), never converted;
- `delay_seconds` carries the provider delay and `source_updated_at` the time the data
  refers to (fetch time minus delay, capped at the session close), so the UI can say
  "atrasado 30 min" or "fechamento de sexta" instead of implying real time;
- nothing runs for a market missing from `MARKETS_ENABLED`.
"""

import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.redis import get_redis
from app.modules.market_data import calendars
from app.modules.market_data.models import Cryptocurrency, MarketTicker
from app.modules.market_data.providers.brapi import BrapiProvider, ExchangeQuote

logger = get_logger(__name__)

B3_MIC = "BVMF"
#: free brapi plan quota; a warning is logged past 80% of it
BRAPI_MONTHLY_QUOTA = 15_000
_CHUNK = 1000
_SYNC_STATUS_KEY = "market:sync:{market}"


def utcnow() -> datetime:
    return datetime.now(UTC)


class MarketDisabledError(Exception):
    """The market is not listed in MARKETS_ENABLED."""


def reference_time(market: str, fetched_at: datetime, delay_seconds: int) -> datetime:
    """When the quote's data was current: fetch time minus the declared delay, but never
    later than the last session close while the market is closed."""
    reference = fetched_at - timedelta(seconds=delay_seconds)
    current = calendars.status(market, fetched_at)
    if current.state == "closed" and current.last_close is not None:
        return min(reference, current.last_close)
    return reference


async def sync_b3(db: AsyncSession, provider: BrapiProvider) -> int:
    if not get_settings().market_enabled("B3"):
        raise MarketDisabledError("B3")
    quotes = await provider.fetch_catalogue()
    fetched_at = utcnow()
    stamp = reference_time("B3", fetched_at, provider.delay_seconds)
    ids = await _store(db, provider.name, quotes, fetched_at, stamp, provider.delay_seconds)
    await db.execute(
        update(Cryptocurrency)
        .where(
            Cryptocurrency.market == "B3",
            Cryptocurrency.source == provider.name,
            Cryptocurrency.source_id.not_in(list(ids)),
        )
        .values(is_active=False)
    )
    await db.commit()
    await _record_usage(provider.requests, fetched_at)
    await get_redis().set(
        _SYNC_STATUS_KEY.format(market="B3"),
        json.dumps({"at": fetched_at.isoformat(), "count": len(quotes), "ok": True}),
    )
    logger.info("b3_sync_completed", instruments=len(quotes), requests=provider.requests)
    return len(quotes)


async def _store(
    db: AsyncSession,
    source: str,
    quotes: Sequence[ExchangeQuote],
    fetched_at: datetime,
    stamp: datetime,
    delay_seconds: int,
) -> dict[str, uuid.UUID]:
    ids: dict[str, uuid.UUID] = {}
    for start in range(0, len(quotes), _CHUNK):
        chunk = quotes[start : start + _CHUNK]
        upsert = insert(Cryptocurrency).values(
            [
                {
                    "source": source,
                    "source_id": q.symbol,
                    "symbol": q.symbol,
                    "name": q.name,
                    "image_url": q.logo_url,
                    "is_active": True,
                    "market": "B3",
                    "asset_type": q.asset_type,
                    "exchange": B3_MIC,
                    "currency": q.currency,
                    "sector": q.sector,
                }
                for q in chunk
            ]
        )
        stmt = upsert.on_conflict_do_update(
            index_elements=[Cryptocurrency.source, Cryptocurrency.source_id],
            set_={
                "name": upsert.excluded.name,
                "image_url": upsert.excluded.image_url,
                "is_active": True,
                "asset_type": upsert.excluded.asset_type,
                "sector": upsert.excluded.sector,
                "updated_at": func.now(),
            },
        ).returning(Cryptocurrency.id, Cryptocurrency.source_id)
        chunk_ids = {source_id: id_ for id_, source_id in (await db.execute(stmt)).all()}
        ids.update(chunk_ids)

        ticker = insert(MarketTicker).values(
            [
                {
                    "cryptocurrency_id": chunk_ids[q.symbol],
                    "quote_currency": q.currency,
                    "price": q.price,
                    "market_cap": q.market_cap,
                    "total_volume": q.volume,
                    # change vs the previous session close
                    "change_pct_24h": q.change_pct,
                    "source": source,
                    "source_updated_at": stamp,
                    "fetched_at": fetched_at,
                    "delay_seconds": delay_seconds,
                }
                for q in chunk
            ]
        )
        await db.execute(
            ticker.on_conflict_do_update(
                index_elements=[MarketTicker.cryptocurrency_id, MarketTicker.quote_currency],
                set_={
                    column: getattr(ticker.excluded, column)
                    for column in (
                        "price",
                        "market_cap",
                        "total_volume",
                        "change_pct_24h",
                        "source",
                        "source_updated_at",
                        "fetched_at",
                        "delay_seconds",
                    )
                },
            )
        )
    return ids


async def _record_usage(requests: int, now: datetime) -> None:
    key = f"brapi:usage:{now:%Y-%m}"
    redis = get_redis()
    used = await redis.incrby(key, requests)
    await redis.expire(key, 40 * 86400)
    if used > BRAPI_MONTHLY_QUOTA * 0.8:
        logger.warning("brapi_quota_high", used=used, quota=BRAPI_MONTHLY_QUOTA)


# --------------------------------------------------------------------------- search


@dataclass(frozen=True, slots=True)
class SearchHit:
    instrument: Cryptocurrency
    ticker: MarketTicker | None


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def search(
    db: AsyncSession, q: str, markets: Sequence[str], limit: int = 20
) -> list[SearchHit]:
    """Instruments across the given (enabled) markets; exact symbol matches first."""
    term = q.strip()
    if not term or not markets:
        return []
    pattern = f"%{_escape_like(term)}%"
    exact = func.upper(Cryptocurrency.symbol) == term.upper()
    rows = (
        await db.execute(
            select(Cryptocurrency, MarketTicker)
            .outerjoin(
                MarketTicker,
                (MarketTicker.cryptocurrency_id == Cryptocurrency.id)
                & (MarketTicker.quote_currency == Cryptocurrency.currency),
            )
            .where(
                Cryptocurrency.market.in_(list(markets)),
                Cryptocurrency.is_active.is_(True),
                Cryptocurrency.symbol.ilike(pattern, escape="\\")
                | Cryptocurrency.name.ilike(pattern, escape="\\"),
            )
            .order_by(
                exact.desc(),
                Cryptocurrency.market_cap_rank.asc().nulls_last(),
                MarketTicker.market_cap.desc().nulls_last(),
                Cryptocurrency.symbol,
            )
            .limit(limit)
        )
    ).all()
    return [SearchHit(instrument, ticker) for instrument, ticker in rows]


async def sync_status(market: str) -> dict[str, object] | None:
    raw = await get_redis().get(_SYNC_STATUS_KEY.format(market=market))
    return json.loads(raw) if raw else None
