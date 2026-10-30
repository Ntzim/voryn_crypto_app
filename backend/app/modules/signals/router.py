import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query

from app.modules.auth.deps import CurrentAuth, DbSession, user_rate_limit
from app.modules.market_data.providers.base import CandleProvider, Timeframe
from app.modules.signals import service
from app.modules.signals.schemas import (
    SignalClass,
    SignalHistoryPoint,
    SignalListOut,
    SignalOut,
    StrategyOut,
)
from app.modules.technical_analysis.router import get_candle_provider
from app.modules.watchlists import service as watchlists

router = APIRouter(prefix="/signals", tags=["signals"])
Provider = Annotated[CandleProvider, Depends(get_candle_provider)]
Slug = Annotated[str, Path(max_length=128, pattern=r"^[a-z0-9-]+$")]


@router.get("")
async def list_signals(
    auth: CurrentAuth,
    db: DbSession,
    timeframe: Timeframe = "1d",
    classification: SignalClass | None = None,
    watchlist_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> SignalListOut:
    """Latest signal per asset (strategy in force), ranked by score."""
    only_ids = None
    if watchlist_id is not None:
        watchlist = await watchlists.get_owned(db, auth.user.id, watchlist_id)
        only_ids = await watchlists.asset_ids(db, watchlist)
    items = await service.list_latest(
        db, timeframe, classification=classification, only_ids=only_ids, limit=limit
    )
    strategy = service.strategy_out(await service.active_strategy(db))
    return SignalListOut(
        items=items, timeframe=timeframe, strategy=strategy, disclaimer=service.DISCLAIMER
    )


@router.get("/strategy")
async def strategy(_: CurrentAuth, db: DbSession) -> StrategyOut:
    return service.strategy_out(await service.active_strategy(db))


@router.get("/{slug}", dependencies=[user_rate_limit("asset_signal", 60, 60)])
async def asset_signal(
    _: CurrentAuth, db: DbSession, provider: Provider, slug: Slug, timeframe: Timeframe = "1d"
) -> SignalOut:
    """Signal for the latest closed candle (generated on demand if not stored yet)."""
    return await service.for_asset(db, slug, timeframe, provider)


@router.get("/{slug}/history")
async def asset_history(
    _: CurrentAuth,
    db: DbSession,
    slug: Slug,
    timeframe: Timeframe = "1d",
    limit: Annotated[int, Query(ge=1, le=365)] = 90,
) -> list[SignalHistoryPoint]:
    return await service.history(db, slug, timeframe, limit)
