from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Path

from app.modules.auth.deps import CurrentAuth, DbSession
from app.modules.market_data.providers.base import CandleProvider, Timeframe
from app.modules.market_data.providers.binance import BinanceCandleProvider
from app.modules.technical_analysis import service
from app.modules.technical_analysis.schemas import AnalysisOut

router = APIRouter(prefix="/market/assets", tags=["technical-analysis"])


async def get_candle_provider() -> AsyncIterator[CandleProvider]:
    provider = BinanceCandleProvider()
    try:
        yield provider
    finally:
        await provider.aclose()


@router.get("/{slug}/analysis")
async def asset_analysis(
    _: CurrentAuth,
    db: DbSession,
    provider: Annotated[CandleProvider, Depends(get_candle_provider)],
    slug: Annotated[str, Path(max_length=128, pattern=r"^[a-z0-9-]+$")],
    timeframe: Timeframe = "1d",
) -> AnalysisOut:
    """Candles + deterministic indicators, trend classification and support/resistance."""
    return await service.asset_analysis(db, slug, timeframe, provider)
