"""Candle retrieval: provider → validation → persistence, with Redis caching and DB fallback.

Safeguards:
- A symbol is mapped to `<SYMBOL>USDT`; the mapping is accepted only if the latest close is
  within 5% of the asset's CoinGecko price. Symbols are not unique in crypto, so this keeps
  a same-ticker token from being charted as the asset.
- Only closed candles are persisted (immutable history for indicators and backtests).
- If the provider is down, stored candles are served and flagged as stale.
"""

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.logging import get_logger
from app.core.redis import get_redis
from app.modules.market_data.models import Cryptocurrency, HistoricalCandle, MarketTicker
from app.modules.market_data.providers.base import (
    TIMEFRAME_SECONDS,
    Candle,
    CandleProvider,
    ProviderError,
    Timeframe,
)
from app.modules.market_data.providers.binance import UnknownPairError

logger = get_logger(__name__)

CANDLE_LIMIT = 500
MAX_PRICE_DEVIATION = Decimal("0.05")
_CACHE_TTL = {"15m": 60, "1h": 120, "4h": 300, "1d": 600, "1w": 1800}
_PAIR_TTL = 24 * 3600
_NO_PAIR = "-"


class CandlesUnavailableError(AppError):
    status_code = 404
    code = "candles_unavailable"
    message = "Não há histórico de candles disponível para este ativo."


@dataclass(frozen=True, slots=True)
class CandleSet:
    candles: list[Candle]
    source: str
    pair: str
    fetched_at: datetime
    #: served from storage because the provider failed, or the latest closed candle is old.
    is_stale: bool


def utcnow() -> datetime:
    return datetime.now(UTC)


def _encode(c: Candle) -> list[str | bool]:
    return [
        c.open_time.isoformat(), str(c.open), str(c.high), str(c.low), str(c.close),
        str(c.volume), str(c.quote_volume), c.closed,
    ]  # fmt: skip


def _decode(row: list[str | bool]) -> Candle:
    return Candle(
        open_time=datetime.fromisoformat(str(row[0])),
        open=Decimal(str(row[1])),
        high=Decimal(str(row[2])),
        low=Decimal(str(row[3])),
        close=Decimal(str(row[4])),
        volume=Decimal(str(row[5])),
        quote_volume=Decimal(str(row[6])),
        closed=bool(row[7]),
    )


def _is_stale(candles: list[Candle], timeframe: Timeframe) -> bool:
    closed = [c for c in candles if c.closed]
    if not closed:
        return True
    interval = timedelta(seconds=TIMEFRAME_SECONDS[timeframe])
    return utcnow() - (closed[-1].open_time + interval) > 2 * interval


async def _stored(db: AsyncSession, crypto_id: object, timeframe: str, limit: int) -> list[Candle]:
    rows = list(
        (
            await db.execute(
                select(HistoricalCandle)
                .where(
                    HistoricalCandle.cryptocurrency_id == crypto_id,
                    HistoricalCandle.timeframe == timeframe,
                )
                .order_by(HistoricalCandle.open_time.desc())
                .limit(limit)
            )
        ).scalars()
    )
    return [
        Candle(r.open_time, r.open, r.high, r.low, r.close, r.volume, r.quote_volume, True)
        for r in reversed(rows)
    ]


async def get_candles(
    db: AsyncSession,
    crypto: Cryptocurrency,
    timeframe: Timeframe,
    provider: CandleProvider,
    limit: int = CANDLE_LIMIT,
) -> CandleSet:
    redis = get_redis()
    cache_key = f"candles:{crypto.id}:{timeframe}"
    if limit != CANDLE_LIMIT:  # longer histories (backtests) are cached separately
        cache_key += f":{limit}"
    pair_key = f"candles:pair:{crypto.id}"

    cached = await redis.get(cache_key)
    if cached:
        payload = json.loads(cached)
        candles = [_decode(r) for r in payload["candles"]]
        return CandleSet(
            candles, payload["source"], payload["pair"],
            datetime.fromisoformat(payload["fetched_at"]), _is_stale(candles, timeframe),
        )  # fmt: skip

    known_pair = await redis.get(pair_key)
    if known_pair == _NO_PAIR:
        raise CandlesUnavailableError()
    pair = known_pair or provider.pair_for(crypto.symbol)
    if pair is None:
        await redis.set(pair_key, _NO_PAIR, ex=_PAIR_TTL)
        raise CandlesUnavailableError()

    try:
        candles = await provider.fetch_candles(pair, timeframe, limit)
    except UnknownPairError:
        await redis.set(pair_key, _NO_PAIR, ex=_PAIR_TTL)
        raise CandlesUnavailableError() from None
    except ProviderError as exc:
        logger.warning("candles_provider_failed", asset=crypto.source_id, error=str(exc))
        stored = await _stored(db, crypto.id, timeframe, limit)
        if not stored:
            raise AppError(
                "Não foi possível obter os candles agora. Tente novamente em instantes.",
                code="candles_provider_unavailable",
                status_code=503,
            ) from exc
        return CandleSet(stored, provider.name, pair, utcnow(), is_stale=True)

    if not candles:
        raise CandlesUnavailableError()

    if not known_pair:
        ticker = (
            await db.execute(
                select(MarketTicker).where(
                    MarketTicker.cryptocurrency_id == crypto.id,
                    MarketTicker.quote_currency == "USD",
                )
            )
        ).scalar_one_or_none()
        if ticker is not None and ticker.price > 0:
            deviation = abs(candles[-1].close - ticker.price) / ticker.price
            if deviation > MAX_PRICE_DEVIATION:
                logger.warning(
                    "candles_pair_mismatch",
                    asset=crypto.source_id,
                    pair=pair,
                    deviation=str(deviation),
                )
                await redis.set(pair_key, _NO_PAIR, ex=_PAIR_TTL)
                raise CandlesUnavailableError(
                    "O mercado de referência encontrado não corresponde a este ativo."
                )
        await redis.set(pair_key, pair, ex=_PAIR_TTL)

    fetched_at = utcnow()
    closed = [c for c in candles if c.closed]
    if closed:
        await db.execute(
            insert(HistoricalCandle)
            .values(
                [
                    {
                        "cryptocurrency_id": crypto.id,
                        "timeframe": timeframe,
                        "open_time": c.open_time,
                        "open": c.open,
                        "high": c.high,
                        "low": c.low,
                        "close": c.close,
                        "volume": c.volume,
                        "quote_volume": c.quote_volume,
                        "source": provider.name,
                        "source_symbol": pair,
                    }
                    for c in closed
                ]
            )
            .on_conflict_do_nothing()
        )
        await db.commit()

    await redis.set(
        cache_key,
        json.dumps(
            {
                "candles": [_encode(c) for c in candles],
                "source": provider.name,
                "pair": pair,
                "fetched_at": fetched_at.isoformat(),
            }
        ),
        ex=_CACHE_TTL[timeframe],
    )
    return CandleSet(candles, provider.name, pair, fetched_at, _is_stale(candles, timeframe))


async def prune_intraday(db: AsyncSession) -> None:
    """Retention: 15m candles 60 days, 1h candles 1 year; 4h/1d/1w are kept."""
    from sqlalchemy import delete

    now = utcnow()
    for timeframe, keep in (("15m", timedelta(days=60)), ("1h", timedelta(days=365))):
        await db.execute(
            delete(HistoricalCandle).where(
                HistoricalCandle.timeframe == timeframe, HistoricalCandle.open_time < now - keep
            )
        )
    await db.commit()
