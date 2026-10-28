"""Market data use-cases: ingestion from providers and read models for the API.

Quotes are ingested once in USD (single source of truth). BRL values are derived with the
latest stored USD→BRL rate, and responses say which rate and timestamp were used.
"""

import json
import uuid
from collections.abc import Sequence
from dataclasses import asdict
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import Select, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError, NotFoundError
from app.core.logging import get_logger
from app.core.redis import get_redis
from app.modules.market_data.models import (
    Cryptocurrency,
    DailyPrice,
    FxRate,
    MarketPrice,
    MarketTicker,
)
from app.modules.market_data.providers.base import (
    FxHistoryProvider,
    MarketDataProvider,
    MarketQuote,
    ProviderError,
)
from app.modules.market_data.schemas import (
    AssetDetailOut,
    AssetListOut,
    AssetOut,
    DataStatus,
    MarketOverviewOut,
    QuoteCurrency,
    SortKey,
)

logger = get_logger(__name__)

BASE_QUOTE = "USD"
ATTRIBUTION = "Dados fornecidos por CoinGecko"
_SYNC_STATUS_KEY = "market:sync_status"
_MONEY_FIELDS = (
    "price",
    "market_cap",
    "fully_diluted_valuation",
    "total_volume",
    "high_24h",
    "low_24h",
    "ath",
)
_QUOTE_FIELDS = (
    "price",
    "market_cap",
    "fully_diluted_valuation",
    "total_volume",
    "high_24h",
    "low_24h",
    "change_pct_1h",
    "change_pct_24h",
    "change_pct_7d",
    "circulating_supply",
    "total_supply",
    "max_supply",
    "ath",
    "ath_change_pct",
    "ath_date",
    "source_updated_at",
)


class MarketDataUnavailableError(AppError):
    status_code = 503
    code = "market_data_unavailable"
    message = "Os dados de mercado ainda não estão disponíveis. Tente novamente em instantes."


class FxUnavailableError(AppError):
    status_code = 503
    code = "fx_unavailable"
    message = "Cotação USD/BRL indisponível no momento. Exiba os valores em USD."


def utcnow() -> datetime:
    return datetime.now(UTC)


# --------------------------------------------------------------------------- ingestion


async def sync_markets(
    db: AsyncSession, provider: MarketDataProvider, extra_source_ids: Sequence[str] = ()
) -> int:
    """Refresh the top-N universe plus any extra assets (e.g. held in portfolios).

    Extra assets get live tickers but stay out of the market listing (`is_active=False`).
    """
    settings = get_settings()
    quotes = await provider.fetch_top_markets(BASE_QUOTE, settings.market_top_n)
    fetched_at = utcnow()
    ids = await _store_quotes(db, provider.name, quotes, fetched_at, active=True)

    # Assets that dropped out of the tracked universe keep history but leave the listing.
    await db.execute(
        update(Cryptocurrency)
        .where(
            Cryptocurrency.source == provider.name,
            Cryptocurrency.source_id.not_in(list(ids)),
        )
        .values(is_active=False, market_cap_rank=None)
    )
    missing = sorted(set(extra_source_ids) - set(ids))
    if missing:
        extras = await provider.fetch_markets_by_ids(BASE_QUOTE, missing)
        if extras:
            await _store_quotes(db, provider.name, extras, fetched_at, active=False)
    await db.commit()

    await get_redis().set(
        _SYNC_STATUS_KEY,
        json.dumps({"at": fetched_at.isoformat(), "count": len(quotes), "ok": True}),
    )
    logger.info(
        "market_sync_completed", provider=provider.name, assets=len(quotes), extra=len(missing)
    )
    return len(quotes)


async def _store_quotes(
    db: AsyncSession,
    source: str,
    quotes: Sequence[MarketQuote],
    fetched_at: datetime,
    *,
    active: bool,
) -> dict[str, uuid.UUID]:
    asset_rows = [
        {
            "source": source,
            "source_id": q.source_id,
            "symbol": q.symbol,
            "name": q.name,
            "image_url": q.image_url,
            "market_cap_rank": q.market_cap_rank if active else None,
            "is_active": active,
        }
        for q in quotes
    ]
    upsert = insert(Cryptocurrency).values(asset_rows)
    stmt = upsert.on_conflict_do_update(
        index_elements=[Cryptocurrency.source, Cryptocurrency.source_id],
        set_={
            "symbol": upsert.excluded.symbol,
            "name": upsert.excluded.name,
            "image_url": upsert.excluded.image_url,
            "market_cap_rank": upsert.excluded.market_cap_rank,
            "is_active": upsert.excluded.is_active,
            "updated_at": func.now(),
        },
    ).returning(Cryptocurrency.id, Cryptocurrency.source_id)
    ids = {source_id: id_ for id_, source_id in (await db.execute(stmt)).all()}

    quote_rows = []
    for q in quotes:
        data = asdict(q)
        quote_rows.append(
            {
                "cryptocurrency_id": ids[q.source_id],
                "quote_currency": q.quote_currency,
                "source": source,
                "fetched_at": fetched_at,
                **{field: data[field] for field in _QUOTE_FIELDS},
            }
        )
    ticker_stmt = insert(MarketTicker).values(quote_rows)
    await db.execute(
        ticker_stmt.on_conflict_do_update(
            index_elements=[MarketTicker.cryptocurrency_id, MarketTicker.quote_currency],
            set_={
                field: ticker_stmt.excluded[field]
                for field in (*_QUOTE_FIELDS, "source", "fetched_at")
            },
        )
    )
    await db.execute(insert(MarketPrice).values(quote_rows).on_conflict_do_nothing())
    return ids


async def record_sync_failure(error: str) -> None:
    await get_redis().set(
        _SYNC_STATUS_KEY,
        json.dumps({"at": utcnow().isoformat(), "ok": False, "error": error[:300]}),
    )


async def sync_fx(db: AsyncSession, provider: MarketDataProvider) -> Decimal:
    fx = await provider.fetch_fx_rate("USD", "BRL")
    await db.execute(
        insert(FxRate)
        .values(
            base_currency=fx.base_currency,
            quote_currency=fx.quote_currency,
            rate=fx.rate,
            source=provider.name,
            observed_at=fx.observed_at,
        )
        .on_conflict_do_nothing()
    )
    await db.commit()
    logger.info("fx_sync_completed", pair="USD/BRL", rate=str(fx.rate))
    return fx.rate


async def prune_history(db: AsyncSession) -> int:
    cutoff = utcnow() - timedelta(days=get_settings().market_history_retention_days)
    result = await db.execute(delete(MarketPrice).where(MarketPrice.fetched_at < cutoff))
    # FX history is tiny and useful for portfolio valuation; keep a year.
    await db.execute(delete(FxRate).where(FxRate.observed_at < utcnow() - timedelta(days=365)))
    await db.commit()
    return int(result.rowcount)  # type: ignore[attr-defined]


# --------------------------------------------------------------------------- read models


async def _latest_fx(db: AsyncSession) -> FxRate | None:
    result = await db.execute(
        select(FxRate)
        .where(FxRate.base_currency == "USD", FxRate.quote_currency == "BRL")
        .order_by(FxRate.observed_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _status(db: AsyncSession, currency: QuoteCurrency) -> tuple[DataStatus, Decimal]:
    settings = get_settings()
    fetched_at = await db.scalar(
        select(func.max(MarketTicker.fetched_at)).where(MarketTicker.quote_currency == BASE_QUOTE)
    )
    fx_rate: Decimal | None = None
    fx_observed_at: datetime | None = None
    multiplier = Decimal(1)
    if currency == "BRL":
        fx = await _latest_fx(db)
        if fx is None:
            raise FxUnavailableError()
        fx_rate, fx_observed_at, multiplier = fx.rate, fx.observed_at, fx.rate
    is_stale = fetched_at is None or (
        utcnow() - fetched_at > timedelta(seconds=settings.market_stale_after_seconds)
    )
    status = DataStatus(
        source="CoinGecko",
        attribution=ATTRIBUTION,
        fetched_at=fetched_at,
        is_stale=is_stale,
        stale_after_seconds=settings.market_stale_after_seconds,
        currency=currency,
        fx_rate=fx_rate,
        fx_observed_at=fx_observed_at,
    )
    return status, multiplier


def _to_asset(crypto: Cryptocurrency, ticker: MarketTicker, multiplier: Decimal) -> AssetOut:
    values = {field: getattr(ticker, field) for field in _QUOTE_FIELDS}
    if multiplier != 1:
        for field in _MONEY_FIELDS:
            if values[field] is not None:
                values[field] = values[field] * multiplier
    return AssetOut(
        id=crypto.id,
        slug=crypto.source_id,
        symbol=crypto.symbol,
        name=crypto.name,
        image_url=crypto.image_url,
        market_cap_rank=crypto.market_cap_rank,
        **values,
    )


def _base_query() -> Select[Cryptocurrency, MarketTicker]:
    return (
        select(Cryptocurrency, MarketTicker)
        .join(MarketTicker, MarketTicker.cryptocurrency_id == Cryptocurrency.id)
        .where(MarketTicker.quote_currency == BASE_QUOTE, Cryptocurrency.is_active.is_(True))
    )


_SORT_COLUMNS = {
    "rank": Cryptocurrency.market_cap_rank,
    "market_cap": MarketTicker.market_cap,
    "price": MarketTicker.price,
    "change_24h": MarketTicker.change_pct_24h,
    "change_7d": MarketTicker.change_pct_7d,
    "volume": MarketTicker.total_volume,
    "name": Cryptocurrency.name,
}


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def list_assets(
    db: AsyncSession,
    *,
    currency: QuoteCurrency,
    q: str | None,
    sort: SortKey,
    order: str,
    page: int,
    page_size: int,
) -> AssetListOut:
    status, multiplier = await _status(db, currency)
    query = _base_query()
    if q:
        pattern = f"%{_escape_like(q.strip())}%"
        query = query.where(
            Cryptocurrency.symbol.ilike(pattern, escape="\\")
            | Cryptocurrency.name.ilike(pattern, escape="\\")
        )
    total = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    column = _SORT_COLUMNS[sort]
    ordering = column.asc() if order == "asc" else column.desc()
    rows = await db.execute(
        query.order_by(ordering.nulls_last(), Cryptocurrency.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return AssetListOut(
        items=[_to_asset(c, t, multiplier) for c, t in rows.all()],
        total=total,
        page=page,
        page_size=page_size,
        status=status,
    )


async def get_asset(db: AsyncSession, slug: str, currency: QuoteCurrency) -> AssetDetailOut:
    status, multiplier = await _status(db, currency)
    row = (
        await db.execute(
            select(Cryptocurrency, MarketTicker)
            .join(MarketTicker, MarketTicker.cryptocurrency_id == Cryptocurrency.id)
            .where(Cryptocurrency.source_id == slug, MarketTicker.quote_currency == BASE_QUOTE)
        )
    ).one_or_none()
    if row is None:
        raise NotFoundError("Ativo não encontrado.")
    return AssetDetailOut(asset=_to_asset(row[0], row[1], multiplier), status=status)


async def overview(db: AsyncSession, currency: QuoteCurrency, movers: int = 5) -> MarketOverviewOut:
    status, multiplier = await _status(db, currency)
    rows = list((await db.execute(_base_query())).all())
    if not rows:
        raise MarketDataUnavailableError()
    assets = [_to_asset(c, t, multiplier) for c, t in rows]
    caps = [a.market_cap for a in assets if a.market_cap is not None]
    total_cap = sum(caps, Decimal(0)) if caps else None
    volumes = [a.total_volume for a in assets if a.total_volume is not None]
    btc = next((a for a in assets if a.slug == "bitcoin"), None)
    dominance = (
        btc.market_cap / total_cap * 100
        if btc and btc.market_cap is not None and total_cap
        else None
    )
    with_change = [a for a in assets if a.change_pct_24h is not None]
    by_change = sorted(with_change, key=lambda a: a.change_pct_24h or Decimal(0))
    return MarketOverviewOut(
        tracked_assets=len(assets),
        total_market_cap=total_cap,
        total_volume_24h=sum(volumes, Decimal(0)) if volumes else None,
        btc_dominance_pct=dominance,
        advancers_24h=sum(1 for a in with_change if (a.change_pct_24h or 0) > 0),
        decliners_24h=sum(1 for a in with_change if (a.change_pct_24h or 0) < 0),
        top_gainers=list(reversed(by_change[-movers:])),
        top_losers=by_change[:movers],
        status=status,
    )


async def sync_status() -> dict[str, object] | None:
    raw = await get_redis().get(_SYNC_STATUS_KEY)
    return json.loads(raw) if raw else None


# --------------------------------------------------------------------------- history


async def backfill_daily_prices(
    db: AsyncSession,
    provider: MarketDataProvider,
    assets: dict[uuid.UUID, str],
    since: date,
) -> int:
    """Fetch missing daily closes from `since` (the free API serves at most 365 days).

    Assets already covered from `since` to yesterday are skipped, so the job is cheap to
    repeat. A failure on one asset is logged and does not stop the others.
    """
    yesterday = utcnow().date() - timedelta(days=1)
    since = max(since, yesterday - timedelta(days=364))
    if not assets or since > yesterday:
        return 0
    bounds = {
        crypto_id: (first, last)
        for crypto_id, first, last in (
            await db.execute(
                select(
                    DailyPrice.cryptocurrency_id,
                    func.min(DailyPrice.day),
                    func.max(DailyPrice.day),
                )
                .where(DailyPrice.cryptocurrency_id.in_(list(assets)))
                .group_by(DailyPrice.cryptocurrency_id)
            )
        ).all()
    }
    stored = 0
    for crypto_id, source_id in assets.items():
        first, last = bounds.get(crypto_id, (None, None))
        if first is not None and last is not None and first <= since and last >= yesterday:
            continue
        try:
            closes = await provider.fetch_daily_closes(
                source_id, (utcnow().date() - since).days + 1
            )
        except ProviderError as exc:
            logger.warning("daily_prices_failed", asset=source_id, error=str(exc))
            continue
        rows = [
            {
                "cryptocurrency_id": crypto_id,
                "day": c.day,
                "close": c.close,
                "source": provider.name,
            }
            for c in closes
            if c.day >= since
        ]
        if rows:
            stmt = insert(DailyPrice).values(rows)
            await db.execute(
                stmt.on_conflict_do_update(
                    index_elements=[DailyPrice.cryptocurrency_id, DailyPrice.day],
                    set_={"close": stmt.excluded.close, "fetched_at": func.now()},
                )
            )
            await db.commit()
            stored += len(rows)
    logger.info("daily_prices_backfilled", assets=len(assets), rows=stored)
    return stored


async def backfill_fx_history(db: AsyncSession, provider: FxHistoryProvider, since: date) -> int:
    """Store official PTAX observations from `since` to today (idempotent)."""
    quotes = await provider.fetch_usd_brl(since, utcnow().date())
    if not quotes:
        return 0
    await db.execute(
        insert(FxRate)
        .values(
            [
                {
                    "base_currency": q.base_currency,
                    "quote_currency": q.quote_currency,
                    "rate": q.rate,
                    "source": provider.name,
                    "observed_at": q.observed_at,
                }
                for q in quotes
            ]
        )
        .on_conflict_do_nothing()
    )
    await db.commit()
    return len(quotes)


# --------------------------------------------------------------------------- read helpers
# Consumed by the portfolio module.

FX_MAX_AGE = timedelta(days=7)


async def usd_brl_at(db: AsyncSession, when: datetime) -> Decimal | None:
    """Latest USD→BRL observation at or before `when`, if not older than 7 days."""
    row = (
        await db.execute(
            select(FxRate.rate, FxRate.observed_at)
            .where(
                FxRate.base_currency == "USD",
                FxRate.quote_currency == "BRL",
                FxRate.observed_at <= when,
            )
            .order_by(FxRate.observed_at.desc())
            .limit(1)
        )
    ).one_or_none()
    if row is None or when - row.observed_at > FX_MAX_AGE:
        return None
    rate: Decimal = row.rate
    return rate


async def usd_brl_daily(db: AsyncSession, start: date, end: date) -> dict[date, Decimal]:
    """USD→BRL at the end of each UTC day in [start, end], carried over weekends/holidays."""
    rows = (
        await db.execute(
            select(FxRate.observed_at, FxRate.rate)
            .where(
                FxRate.base_currency == "USD",
                FxRate.quote_currency == "BRL",
                FxRate.observed_at < datetime.combine(end + timedelta(days=1), time(), UTC),
                FxRate.observed_at >= datetime.combine(start, time(), UTC) - FX_MAX_AGE,
            )
            .order_by(FxRate.observed_at)
        )
    ).all()
    result: dict[date, Decimal] = {}
    index, current = 0, None
    day = start
    while day <= end:
        day_end = datetime.combine(day + timedelta(days=1), time(), UTC)
        while index < len(rows) and rows[index].observed_at < day_end:
            current = rows[index].rate
            index += 1
        if current is not None:
            result[day] = current
        day += timedelta(days=1)
    return result


async def daily_closes(
    db: AsyncSession, crypto_ids: Sequence[uuid.UUID], start: date, end: date
) -> dict[uuid.UUID, dict[date, Decimal]]:
    rows = (
        await db.execute(
            select(DailyPrice.cryptocurrency_id, DailyPrice.day, DailyPrice.close).where(
                DailyPrice.cryptocurrency_id.in_(list(crypto_ids)),
                DailyPrice.day >= start,
                DailyPrice.day <= end,
            )
        )
    ).all()
    result: dict[uuid.UUID, dict[date, Decimal]] = {}
    for crypto_id, day, close in rows:
        result.setdefault(crypto_id, {})[day] = close
    return result


async def live_tickers(
    db: AsyncSession, crypto_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, MarketTicker]:
    rows = (
        await db.execute(
            select(MarketTicker).where(
                MarketTicker.cryptocurrency_id.in_(list(crypto_ids)),
                MarketTicker.quote_currency == BASE_QUOTE,
            )
        )
    ).scalars()
    return {t.cryptocurrency_id: t for t in rows}


async def cryptos_by_id(
    db: AsyncSession, crypto_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, Cryptocurrency]:
    rows = (
        await db.execute(select(Cryptocurrency).where(Cryptocurrency.id.in_(list(crypto_ids))))
    ).scalars()
    return {c.id: c for c in rows}


async def resolve_asset(db: AsyncSession, ref: str) -> Cryptocurrency | None:
    """Resolve a slug ("bitcoin") or a symbol ("BTC"); a symbol picks the best-ranked match."""
    ref = ref.strip()
    by_slug = (
        await db.execute(select(Cryptocurrency).where(Cryptocurrency.source_id == ref.lower()))
    ).scalar_one_or_none()
    if by_slug is not None:
        return by_slug
    return (
        await db.execute(
            select(Cryptocurrency)
            .where(func.upper(Cryptocurrency.symbol) == ref.upper())
            .order_by(Cryptocurrency.market_cap_rank.asc().nulls_last())
            .limit(1)
        )
    ).scalar_one_or_none()


async def search_assets(db: AsyncSession, q: str, limit: int = 10) -> list[Cryptocurrency]:
    pattern = f"%{_escape_like(q.strip())}%"
    return list(
        (
            await db.execute(
                select(Cryptocurrency)
                .where(
                    Cryptocurrency.symbol.ilike(pattern, escape="\\")
                    | Cryptocurrency.name.ilike(pattern, escape="\\")
                )
                .order_by(Cryptocurrency.market_cap_rank.asc().nulls_last(), Cryptocurrency.name)
                .limit(limit)
            )
        ).scalars()
    )
