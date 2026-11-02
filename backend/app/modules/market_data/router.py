import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query

from app.core.config import get_settings
from app.modules.auth.deps import CurrentAuth, DbSession, user_rate_limit
from app.modules.market_data import calendars, exchanges, service
from app.modules.market_data.providers import brapi
from app.modules.market_data.schemas import (
    AssetBriefOut,
    AssetDetailOut,
    AssetListOut,
    ExchangeAssetListOut,
    ExchangeDetailOut,
    ExchangeHistoryOut,
    ExchangeOverviewOut,
    InstrumentHitOut,
    Market,
    MarketOut,
    MarketOverviewOut,
    QuoteCurrency,
    SortKey,
)
from app.modules.watchlists import service as watchlists

router = APIRouter(prefix="/market", tags=["market"])


@router.get("/assets")
async def list_assets(
    auth: CurrentAuth,
    db: DbSession,
    currency: QuoteCurrency = "USD",
    q: Annotated[str | None, Query(max_length=64)] = None,
    sort: SortKey = "rank",
    order: Literal["asc", "desc"] = "asc",
    page: Annotated[int, Query(ge=1, le=1000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
    watchlist_id: uuid.UUID | None = None,
) -> AssetListOut:
    only_ids = None
    if watchlist_id is not None:
        watchlist = await watchlists.get_owned(db, auth.user.id, watchlist_id)
        only_ids = await watchlists.asset_ids(db, watchlist)
    return await service.list_assets(
        db,
        currency=currency,
        q=q,
        sort=sort,
        order=order,
        page=page,
        page_size=page_size,
        only_ids=only_ids,
    )


@router.get("/search")
async def search_assets(
    _: CurrentAuth, db: DbSession, q: Annotated[str, Query(min_length=1, max_length=64)]
) -> list[AssetBriefOut]:
    """Asset picker: catalogue search by name or symbol, best-ranked first."""
    return [
        AssetBriefOut(
            id=c.id, slug=c.source_id, symbol=c.symbol, name=c.name, image_url=c.image_url
        )
        for c in await service.search_assets(db, q)
    ]


@router.get("/assets/{slug}")
async def get_asset(
    _: CurrentAuth,
    db: DbSession,
    slug: Annotated[str, Path(max_length=128, pattern=r"^[a-z0-9-]+$")],
    currency: QuoteCurrency = "USD",
) -> AssetDetailOut:
    return await service.get_asset(db, slug, currency)


@router.get("/overview")
async def overview(
    _: CurrentAuth, db: DbSession, currency: QuoteCurrency = "USD"
) -> MarketOverviewOut:
    return await service.overview(db, currency)


_MARKET_LABELS = {"CRYPTO": "Criptomoedas", "B3": "B3 — Bolsa brasileira", "US": "Bolsas dos EUA"}


@router.get("/markets")
async def list_markets(_: CurrentAuth) -> list[MarketOut]:
    """Enabled markets with session state, quote delay and data attribution."""
    settings = get_settings()
    now = datetime.now(UTC)
    out: list[MarketOut] = []
    for market in settings.markets_enabled:
        if market == "US":
            continue  # no US data provider yet (needs a commercial display license)
        state = calendars.status(market, now)
        if market == "CRYPTO":
            status = await service.sync_status()
            currency, delay, attribution = "USD", 0, service.ATTRIBUTION
        else:
            status = await exchanges.sync_status(market)
            currency = "BRL"
            delay = brapi.DELAY_SECONDS[settings.brapi_plan]
            attribution = brapi.ATTRIBUTION
        at = status.get("at") if status else None
        out.append(
            MarketOut(
                market=market,
                label=_MARKET_LABELS[market],
                currency=currency,
                state=state.state,
                last_close=state.last_close,
                next_open=state.next_open,
                delay_seconds=delay,
                attribution=attribution,
                last_sync_at=datetime.fromisoformat(at) if isinstance(at, str) else None,
            )
        )
    return out


@router.get("/instruments/search")
async def search_instruments(
    _: CurrentAuth,
    db: DbSession,
    q: Annotated[str, Query(min_length=1, max_length=64)],
    market: Market | None = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> list[InstrumentHitOut]:
    """Global search across the enabled markets (disabled markets are never returned)."""
    enabled = get_settings().markets_enabled
    markets = [m for m in enabled if market is None or m == market]
    return [
        InstrumentHitOut(
            id=hit.instrument.id,
            market=hit.instrument.market,
            asset_type=hit.instrument.asset_type,
            exchange=hit.instrument.exchange,
            symbol=hit.instrument.symbol,
            slug=hit.instrument.source_id,
            name=hit.instrument.name,
            image_url=hit.instrument.image_url,
            currency=hit.instrument.currency,
            price=hit.ticker.price if hit.ticker else None,
            change_pct=hit.ticker.change_pct_24h if hit.ticker else None,
            delay_seconds=hit.ticker.delay_seconds if hit.ticker else None,
            as_of=hit.ticker.source_updated_at if hit.ticker else None,
        )
        for hit in await exchanges.search(db, q, markets, limit)
    ]


# --------------------------------------------------------------------------- exchange markets

ExchangeMarket = Literal["B3"]
Symbol = Annotated[str, Path(pattern=r"^[A-Z0-9]{4,12}$")]


async def get_brapi_provider() -> AsyncIterator[brapi.BrapiProvider]:
    # A page view makes one attempt; backing off would hold the request open for seconds.
    provider = brapi.BrapiProvider(max_attempts=1)
    try:
        yield provider
    finally:
        await provider.aclose()


Brapi = Annotated[brapi.BrapiProvider, Depends(get_brapi_provider)]


@router.get("/exchanges/{market}/overview")
async def exchange_overview(
    _: CurrentAuth, db: DbSession, market: ExchangeMarket
) -> ExchangeOverviewOut:
    exchanges.ensure_enabled(market)
    return await exchanges.overview(db, market)


@router.get("/exchanges/{market}/assets")
async def exchange_assets(
    _: CurrentAuth,
    db: DbSession,
    market: ExchangeMarket,
    q: Annotated[str | None, Query(max_length=64)] = None,
    asset_type: Literal["STOCK", "FII", "ETF", "BDR"] | None = None,
    sort: exchanges.ExchangeSort = "market_cap",
    order: Literal["asc", "desc"] = "desc",
    page: Annotated[int, Query(ge=1, le=1000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> ExchangeAssetListOut:
    exchanges.ensure_enabled(market)
    return await exchanges.list_assets(
        db,
        market,
        q=q,
        asset_type=asset_type,
        sort=sort,
        order=order,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/exchanges/{market}/assets/{symbol}",
    dependencies=[user_rate_limit("exchange_detail", 60, 60)],
)
async def exchange_asset(
    _: CurrentAuth, db: DbSession, market: ExchangeMarket, symbol: Symbol, provider: Brapi
) -> ExchangeDetailOut:
    exchanges.ensure_enabled(market)
    return await exchanges.detail(db, market, symbol, provider)


@router.get(
    "/exchanges/{market}/assets/{symbol}/history",
    dependencies=[user_rate_limit("exchange_history", 60, 60)],
)
async def exchange_asset_history(
    _: CurrentAuth,
    db: DbSession,
    market: ExchangeMarket,
    symbol: Symbol,
    provider: Brapi,
    range: Literal["1mo", "3mo", "1y", "5y"] = "3mo",
) -> ExchangeHistoryOut:
    exchanges.ensure_enabled(market)
    return await exchanges.history(db, market, symbol, range, provider)
