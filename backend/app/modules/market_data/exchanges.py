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
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import Select, case, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError, NotFoundError
from app.core.logging import get_logger
from app.core.redis import get_redis
from app.modules.market_data import calendars
from app.modules.market_data.models import Cryptocurrency, MarketTicker
from app.modules.market_data.providers import brapi
from app.modules.market_data.providers.base import ProviderError
from app.modules.market_data.providers.brapi import (
    BrapiProvider,
    DailyBar,
    ExchangeQuote,
    ProviderAccessError,
    ProviderNotFoundError,
    ProviderPlanError,
    ProviderRateLimitError,
    SessionDetail,
)
from app.modules.market_data.schemas import (
    DailyBarOut,
    ExchangeAssetListOut,
    ExchangeAssetOut,
    ExchangeDetailOut,
    ExchangeHistoryOut,
    ExchangeOverviewOut,
    ExchangeStatusOut,
    UnavailableReason,
)

logger = get_logger(__name__)

B3_MIC = "BVMF"
#: free brapi plan quota; a warning is logged past 80% of it
BRAPI_MONTHLY_QUOTA = 15_000
_CHUNK = 1000
_SYNC_STATUS_KEY = "market:sync:{market}"


def utcnow() -> datetime:
    return datetime.now(UTC)


class MarketDisabledError(AppError):
    """The market is not listed in MARKETS_ENABLED."""

    status_code = 404
    code = "market_disabled"
    message = "Este mercado ainda não está disponível."


def ensure_enabled(market: str) -> None:
    if not get_settings().market_enabled(market):
        raise MarketDisabledError()


def reference_time(market: str, fetched_at: datetime, delay_seconds: int) -> datetime:
    """When the quote's data was current: fetch time minus the declared delay, but never
    later than the last session close while the market is closed."""
    reference = fetched_at - timedelta(seconds=delay_seconds)
    current = calendars.status(market, fetched_at)
    if current.state == "closed" and current.last_close is not None:
        return min(reference, current.last_close)
    return reference


async def sync_b3(db: AsyncSession, provider: BrapiProvider) -> int:
    ensure_enabled("B3")
    wait = await blocked_for()
    if wait:
        raise ProviderRateLimitError(wait, "/v2/tickers", "BLOCKED_BY_RETRY_AFTER")
    try:
        quotes = await provider.fetch_catalogue()
    except ProviderRateLimitError as exc:
        await block(exc.retry_after)
        raise
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
    await record_usage(provider.requests, fetched_at)
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


async def record_usage(requests: int, now: datetime) -> None:
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


# --------------------------------------------------------------------------- exploration

#: Movers and breadth only count instruments that really traded: on illiquid tickers a single
#: small order moves the price tens of percent, which says nothing about the market.
MIN_TRADED_VALUE = Decimal(1_000_000)
#: ETF shown as the index reference, labeled as an ETF (index values are licensed data).
REFERENCE_SYMBOL = "BOVA11"
_DETAIL_TTL_SECONDS = 15 * 60
_HISTORY_TTL_SECONDS = 6 * 3600
_ACCESS_DENIED_TTL_SECONDS = 3600
_FAILURE_TTL_SECONDS = 60
_BLOCK_KEY = "brapi:blocked"

ExchangeSort = Literal["market_cap", "traded_value", "change", "price", "name"]

_traded_value = MarketTicker.price * MarketTicker.total_volume
_SORTS: dict[str, Any] = {
    "market_cap": MarketTicker.market_cap,
    "traded_value": _traded_value,
    "change": MarketTicker.change_pct_24h,
    "price": MarketTicker.price,
    "name": Cryptocurrency.name,
}


def _rows(market: str) -> Select[Cryptocurrency, MarketTicker]:
    return (
        select(Cryptocurrency, MarketTicker)
        .join(
            MarketTicker,
            (MarketTicker.cryptocurrency_id == Cryptocurrency.id)
            & (MarketTicker.quote_currency == Cryptocurrency.currency),
        )
        .where(Cryptocurrency.market == market, Cryptocurrency.is_active.is_(True))
    )


def _asset(instrument: Cryptocurrency, ticker: MarketTicker) -> ExchangeAssetOut:
    volume = ticker.total_volume
    return ExchangeAssetOut(
        id=instrument.id,
        symbol=instrument.symbol,
        name=instrument.name,
        asset_type=instrument.asset_type,
        exchange=instrument.exchange,
        sector=instrument.sector,
        image_url=instrument.image_url,
        currency=instrument.currency,
        price=ticker.price,
        change_pct=ticker.change_pct_24h,
        volume=volume,
        traded_value=ticker.price * volume if volume is not None else None,
        market_cap=ticker.market_cap,
    )


async def market_status(db: AsyncSession, market: str) -> ExchangeStatusOut:
    settings = get_settings()
    now = utcnow()
    session = calendars.status(market, now)
    delay = brapi.DELAY_SECONDS[settings.brapi_plan]
    as_of, fetched_at = (
        await db.execute(
            select(func.max(MarketTicker.source_updated_at), func.max(MarketTicker.fetched_at))
            .join(Cryptocurrency, Cryptocurrency.id == MarketTicker.cryptocurrency_id)
            .where(Cryptocurrency.market == market)
        )
    ).one()
    # A quote may lag by the declared delay plus two missed syncs before it counts as stale.
    max_age = timedelta(seconds=delay + 2 * settings.b3_sync_interval_seconds)
    return ExchangeStatusOut(
        market="B3",
        currency="BRL",
        state=session.state,
        last_close=session.last_close,
        next_open=session.next_open,
        delay_seconds=delay,
        as_of=as_of,
        fetched_at=fetched_at,
        is_stale=as_of is None or calendars.is_stale(market, as_of, now, max_age),
        attribution=brapi.ATTRIBUTION,
    )


async def list_assets(
    db: AsyncSession,
    market: str,
    *,
    q: str | None = None,
    asset_type: str | None = None,
    sort: ExchangeSort = "traded_value",
    order: Literal["asc", "desc"] = "desc",
    page: int = 1,
    page_size: int = 50,
) -> ExchangeAssetListOut:
    query = _rows(market)
    if asset_type:
        query = query.where(Cryptocurrency.asset_type == asset_type)
    if q and q.strip():
        pattern = f"%{_escape_like(q.strip())}%"
        query = query.where(
            Cryptocurrency.symbol.ilike(pattern, escape="\\")
            | Cryptocurrency.name.ilike(pattern, escape="\\")
        )
    total = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    column = _SORTS[sort]
    ordering = column.asc() if order == "asc" else column.desc()
    rows = await db.execute(
        query.order_by(ordering.nulls_last(), Cryptocurrency.symbol)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return ExchangeAssetListOut(
        items=[_asset(instrument, ticker) for instrument, ticker in rows.all()],
        total=total,
        page=page,
        page_size=page_size,
        status=await market_status(db, market),
    )


async def most_traded(
    db: AsyncSession, market: str, asset_type: str, limit: int
) -> list[tuple[Cryptocurrency, MarketTicker]]:
    rows = await db.execute(
        _rows(market)
        .where(Cryptocurrency.asset_type == asset_type, _traded_value >= MIN_TRADED_VALUE)
        .order_by(_traded_value.desc())
        .limit(limit)
    )
    return [(row[0], row[1]) for row in rows.all()]


async def breadth_pct(db: AsyncSession, market: str) -> Decimal | None:
    """Share of liquid instruments that rose in the last session, 0-100."""
    change = MarketTicker.change_pct_24h
    up, down = (
        await db.execute(
            _rows(market)
            .where(_traded_value >= MIN_TRADED_VALUE)
            .with_only_columns(
                func.coalesce(func.sum(case((change > 0, 1), else_=0)), 0),
                func.coalesce(func.sum(case((change < 0, 1), else_=0)), 0),
            )
        )
    ).one()
    total = int(up) + int(down)
    return Decimal(int(up)) / total * 100 if total else None


async def overview(db: AsyncSession, market: str, movers: int = 5) -> ExchangeOverviewOut:
    count_rows = await db.execute(
        select(Cryptocurrency.asset_type, func.count())
        .where(Cryptocurrency.market == market, Cryptocurrency.is_active.is_(True))
        .group_by(Cryptocurrency.asset_type)
    )
    counts = {asset_type: count for asset_type, count in count_rows.all()}
    liquid = _traded_value >= MIN_TRADED_VALUE
    change = MarketTicker.change_pct_24h
    advancers, decliners = (
        await db.execute(
            _rows(market)
            .where(liquid)
            .with_only_columns(
                func.coalesce(func.sum(case((change > 0, 1), else_=0)), 0),
                func.coalesce(func.sum(case((change < 0, 1), else_=0)), 0),
            )
        )
    ).one()

    async def top(*ordering: Any, where: Any = None) -> list[ExchangeAssetOut]:
        query = _rows(market).where(liquid)
        if where is not None:
            query = query.where(where)
        rows = await db.execute(query.order_by(*ordering).limit(movers))
        return [_asset(instrument, ticker) for instrument, ticker in rows.all()]

    reference = (
        await db.execute(_rows(market).where(Cryptocurrency.symbol == REFERENCE_SYMBOL))
    ).first()
    return ExchangeOverviewOut(
        status=await market_status(db, market),
        reference=_asset(reference[0], reference[1]) if reference else None,
        counts=counts,
        advancers=int(advancers),
        decliners=int(decliners),
        top_gainers=await top(change.desc(), where=change > 0),
        top_losers=await top(change.asc(), where=change < 0),
        most_traded=await top(_traded_value.desc()),
    )


async def instrument(
    db: AsyncSession, market: str, symbol: str
) -> tuple[Cryptocurrency, MarketTicker]:
    row = (await db.execute(_rows(market).where(Cryptocurrency.symbol == symbol))).first()
    if row is None:
        raise NotFoundError("Ativo não encontrado.")
    return row[0], row[1]


async def quota_reached(now: datetime) -> bool:
    # Only the free plan's quota is known; paid plans are metered by brapi itself.
    if get_settings().brapi_plan != "free":
        return False
    used = await get_redis().get(f"brapi:usage:{now:%Y-%m}")
    return used is not None and int(used) >= BRAPI_MONTHLY_QUOTA


async def blocked_for() -> int:
    """Seconds left of a Retry-After. It applies to the whole account, so every caller waits."""
    ttl = int(await get_redis().ttl(_BLOCK_KEY))
    return max(ttl, 0)


async def block(seconds: int) -> None:
    await get_redis().set(_BLOCK_KEY, "1", ex=max(seconds, 1))


async def _cached_upstream[T](
    key: str,
    ttl: int,
    provider: BrapiProvider,
    fetch: Callable[[], Awaitable[T]],
    encode: Callable[[Any], Any],
    decode: Callable[[Any], T],
) -> tuple[T | None, UnavailableReason | None]:
    """On-demand brapi data through Redis. Failures are cached too, so a page view can never
    turn a missing token or an outage into a burst of metered requests. The token flag is in
    the key: adding a token takes effect right away."""
    redis = get_redis()
    full_key = f"{key}:{'t' if get_settings().brapi_token else 'a'}"
    cached = await redis.get(full_key)
    if cached:
        data = json.loads(cached)
        if data.get("unavailable"):
            return None, data["unavailable"]
        return decode(data["value"]), None

    now = utcnow()
    if await blocked_for():
        return None, "rate_limited"
    if await quota_reached(now):
        return None, "quota_reached"
    reason: UnavailableReason
    try:
        value = await fetch()
    except ProviderRateLimitError as exc:
        logger.warning("brapi_rate_limited", key=key, retry_after=exc.retry_after)
        await record_usage(provider.requests, now)
        await block(exc.retry_after)
        return None, "rate_limited"
    except ProviderAccessError as exc:
        logger.warning("brapi_access_denied", key=key, error=str(exc))
        reason, failure_ttl = "token_required", _ACCESS_DENIED_TTL_SECONDS
    except ProviderPlanError as exc:
        logger.info("brapi_plan_limit", key=key, error=str(exc))
        reason, failure_ttl = "plan_required", _ACCESS_DENIED_TTL_SECONDS
    except ProviderNotFoundError:
        reason, failure_ttl = "no_data", _ACCESS_DENIED_TTL_SECONDS
    except ProviderError as exc:
        logger.warning("brapi_request_failed", key=key, error=str(exc))
        reason, failure_ttl = "provider_unavailable", _FAILURE_TTL_SECONDS
    else:
        await record_usage(provider.requests, now)
        await redis.set(full_key, json.dumps({"value": encode(value)}), ex=ttl)
        return value, None
    await record_usage(provider.requests, now)
    await redis.set(full_key, json.dumps({"unavailable": reason}), ex=failure_ttl)
    return None, reason


def _decimal(value: str | None) -> Decimal | None:
    return Decimal(value) if value is not None else None


async def detail(
    db: AsyncSession, market: str, symbol: str, provider: BrapiProvider
) -> ExchangeDetailOut:
    row, ticker = await instrument(db, market, symbol)
    fields = ("open", "day_high", "day_low", "previous_close", "week52_low", "week52_high")

    def encode(value: SessionDetail) -> dict[str, str | None]:
        raw = {name: getattr(value, name) for name in fields}
        return {name: str(item) if item is not None else None for name, item in raw.items()}

    def decode(data: dict[str, str | None]) -> SessionDetail:
        return SessionDetail(**{name: _decimal(data.get(name)) for name in fields})

    session, unavailable = await _cached_upstream(
        f"b3:detail:{symbol}",
        _DETAIL_TTL_SECONDS,
        provider,
        lambda: provider.fetch_session_detail(symbol),
        encode,
        decode,
    )
    return ExchangeDetailOut(
        asset=_asset(row, ticker),
        open=session.open if session else None,
        day_high=session.day_high if session else None,
        day_low=session.day_low if session else None,
        previous_close=session.previous_close if session else None,
        week52_low=session.week52_low if session else None,
        week52_high=session.week52_high if session else None,
        detail_unavailable=unavailable,
        status=await market_status(db, market),
    )


async def history(
    db: AsyncSession, market: str, symbol: str, range_: str, provider: BrapiProvider
) -> ExchangeHistoryOut:
    await instrument(db, market, symbol)
    allowed = brapi.HISTORY_RANGES[get_settings().brapi_plan]
    if range_ not in allowed:
        raise AppError("Período indisponível no plano de dados atual.", code="range_not_allowed")

    def encode(bars: list[DailyBar]) -> list[dict[str, str | None]]:
        return [
            {
                "day": bar.day.isoformat(),
                "open": str(bar.open),
                "high": str(bar.high),
                "low": str(bar.low),
                "close": str(bar.close),
                "volume": str(bar.volume) if bar.volume is not None else None,
            }
            for bar in bars
        ]

    def decode(rows: list[dict[str, Any]]) -> list[DailyBar]:
        return [
            DailyBar(
                date.fromisoformat(row["day"]),
                Decimal(row["open"]),
                Decimal(row["high"]),
                Decimal(row["low"]),
                Decimal(row["close"]),
                None,
                _decimal(row["volume"]),
            )
            for row in rows
        ]

    bars, unavailable = await _cached_upstream(
        f"b3:history:{symbol}:{range_}",
        _HISTORY_TTL_SECONDS,
        provider,
        lambda: provider.fetch_daily_history(symbol, range_),
        encode,
        decode,
    )
    return ExchangeHistoryOut(
        symbol=symbol,
        range=range_,
        allowed_ranges=list(allowed),
        bars=[
            DailyBarOut(
                day=bar.day,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
            )
            for bar in bars or []
        ],
        unavailable=unavailable,
    )
