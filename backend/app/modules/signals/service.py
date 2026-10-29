"""Signal generation and read models.

Signals are computed on the last *closed* candle and stored once per candle, so the
history shows exactly what the strategy said at each point in time.
"""

import json
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import distinct_on, insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, NotFoundError
from app.core.logging import get_logger
from app.core.redis import get_redis
from app.modules.market_data import candles as candle_service
from app.modules.market_data import service as market
from app.modules.market_data.models import Cryptocurrency, MarketTicker
from app.modules.market_data.providers.base import (
    TIMEFRAME_SECONDS,
    CandleProvider,
    ProviderError,
    Timeframe,
)
from app.modules.portfolio.insights import STABLECOINS
from app.modules.portfolio.schemas import AssetRef
from app.modules.signals import engine
from app.modules.signals.models import AnalysisSignal, SignalStrategy
from app.modules.signals.schemas import (
    COMPONENT_LABELS,
    ComponentOut,
    SignalHistoryPoint,
    SignalOut,
    StrategyOut,
)
from app.modules.technical_analysis.service import METHODOLOGY_VERSION, analyze

logger = get_logger(__name__)

DEFAULT_KEY = "voryn-core"
SCHEDULED_TIMEFRAMES: tuple[Timeframe, ...] = ("1d", "4h")
UNIVERSE_TOP_N = 50
DISCLAIMER = (
    "Sinais analíticos gerados por regras quantitativas a partir de dados históricos. "
    "O score mede o alinhamento de condições favoráveis e não é probabilidade de lucro. "
    "Não constituem recomendação de investimento."
)


def looks_pegged(close: Decimal, volatility_pct: Decimal | None) -> bool:
    """Dollar-pegged by behaviour: within 2% of US$ 1 with annualized volatility under 5%.

    Complements the symbol list, which can never be complete.
    """
    return volatility_pct is not None and volatility_pct < 5 and abs(close - 1) <= Decimal("0.02")


class StablecoinError(AppError):
    status_code = 404
    code = "signal_not_applicable"
    message = "Stablecoins acompanham o dólar e não recebem sinais de oportunidade."


class SignalUnavailableError(AppError):
    status_code = 404
    code = "signal_unavailable"
    message = "Não há dados suficientes para gerar um sinal para este ativo."


def utcnow() -> datetime:
    return datetime.now(UTC)


# --------------------------------------------------------------------------- strategy


async def active_strategy(db: AsyncSession) -> SignalStrategy:
    strategy = (
        await db.execute(
            select(SignalStrategy)
            .where(SignalStrategy.is_active.is_(True))
            .order_by(SignalStrategy.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if strategy is None:
        # Seeded by migration in real databases; created lazily for fresh test databases.
        strategy = SignalStrategy(
            key=DEFAULT_KEY,
            version=1,
            name="Voryn Core v1",
            weights={k: str(v) for k, v in engine.DEFAULT_WEIGHTS.items()},
            thresholds={k: str(v) for k, v in engine.DEFAULT_THRESHOLDS.items()},
            is_active=True,
        )
        db.add(strategy)
        await db.commit()
    return strategy


def strategy_params(strategy: SignalStrategy) -> tuple[dict[str, Decimal], dict[str, Decimal]]:
    weights = {k: Decimal(str(strategy.weights[k])) for k in engine.COMPONENTS}
    if any(w < 0 for w in weights.values()) or sum(weights.values()) <= 0:
        raise ValueError(f"strategy {strategy.key} v{strategy.version} has invalid weights")
    thresholds = {k: Decimal(str(strategy.thresholds[k])) for k in ("buy", "sell")}
    return weights, thresholds


def strategy_out(strategy: SignalStrategy) -> StrategyOut:
    weights, thresholds = strategy_params(strategy)
    total = sum(weights.values())
    return StrategyOut(
        key=strategy.key,
        version=strategy.version,
        name=strategy.name,
        weights_pct={k: (w / total * 100).quantize(Decimal("0.1")) for k, w in weights.items()},
        buy_threshold=thresholds["buy"],
        sell_threshold=thresholds["sell"],
    )


# --------------------------------------------------------------------------- context


async def market_context(
    db: AsyncSession, provider: CandleProvider, timeframe: Timeframe
) -> engine.MarketContext:
    """Breadth of the tracked universe + Bitcoin's trend on the same timeframe (cached 10 min)."""
    key = f"signals:context:{timeframe}"
    cached = await get_redis().get(key)
    if cached:
        data = json.loads(cached)
        breadth = Decimal(data["breadth"]) if data["breadth"] is not None else None
        return engine.MarketContext(breadth, data["btc_trend"])

    changes = list(
        (
            await db.execute(
                select(MarketTicker.change_pct_24h)
                .join(Cryptocurrency, Cryptocurrency.id == MarketTicker.cryptocurrency_id)
                .where(
                    Cryptocurrency.is_active.is_(True),
                    MarketTicker.quote_currency == "USD",
                    MarketTicker.change_pct_24h.is_not(None),
                )
            )
        ).scalars()
    )
    positive = sum(1 for c in changes if c is not None and c > 0)
    breadth = Decimal(positive) / len(changes) * 100 if changes else None
    btc_trend = None
    btc = await market.resolve_asset(db, "bitcoin")
    if btc is not None:
        try:
            result = analyze(
                (await candle_service.get_candles(db, btc, timeframe, provider)).candles, timeframe
            )
            btc_trend = result.trend.classification if result.trend else None
        except (AppError, ProviderError):
            btc_trend = None
    await get_redis().set(
        key,
        json.dumps(
            {"breadth": str(breadth) if breadth is not None else None, "btc_trend": btc_trend}
        ),
        ex=600,
    )
    return engine.MarketContext(breadth, btc_trend)


# --------------------------------------------------------------------------- generation


async def generate(
    db: AsyncSession,
    crypto: Cryptocurrency,
    timeframe: Timeframe,
    provider: CandleProvider,
    strategy: SignalStrategy,
    context: engine.MarketContext,
) -> AnalysisSignal:
    if crypto.symbol.upper() in STABLECOINS:
        raise StablecoinError()
    candle_set = await candle_service.get_candles(db, crypto, timeframe, provider)
    closed = [c for c in candle_set.candles if c.closed]
    result = analyze(closed, timeframe)
    if not closed or result.snapshot is None or result.trend is None:
        raise SignalUnavailableError()
    if looks_pegged(result.snapshot.close, result.snapshot.volatility_annualized_pct):
        raise StablecoinError()
    weights, thresholds = strategy_params(strategy)
    last = closed[-1]
    signal = engine.evaluate(
        snapshot=result.snapshot,
        trend=result.trend,
        supports=result.supports,
        resistances=result.resistances,
        bandwidth_percentile=result.bandwidth_percentile,
        last_candle_up=last.close >= last.open,
        market=context,
        stale=candle_set.is_stale,
        weights=weights,
        thresholds=thresholds,
    )
    await db.execute(
        insert(AnalysisSignal)
        .values(
            cryptocurrency_id=crypto.id,
            timeframe=timeframe,
            strategy_id=strategy.id,
            candle_time=last.open_time,
            reference_price=last.close,
            score=signal.score,
            classification=signal.classification,
            components=[
                {"key": c.key, "score": str(c.score), "weight": str(c.weight), "detail": c.detail}
                for c in signal.components
            ],
            indicators=result.snapshot.model_dump(mode="json"),
            trend=result.trend.classification,
            justification=signal.justification,
            risks=signal.risks,
            invalidation=signal.invalidation,
            data_source=f"{candle_set.source}:{candle_set.pair}",
            data_fetched_at=candle_set.fetched_at,
            data_is_stale=candle_set.is_stale,
            methodology_version=METHODOLOGY_VERSION,
        )
        .on_conflict_do_nothing()
    )
    await db.commit()
    stored = (
        await db.execute(
            select(AnalysisSignal).where(
                AnalysisSignal.cryptocurrency_id == crypto.id,
                AnalysisSignal.timeframe == timeframe,
                AnalysisSignal.strategy_id == strategy.id,
                AnalysisSignal.candle_time == last.open_time,
            )
        )
    ).scalar_one()
    return stored


async def universe(db: AsyncSession) -> dict[uuid.UUID, Cryptocurrency]:
    """Top-N by market cap + every asset someone holds, watches or has alerts on."""
    from app.modules.alerts.models import Alert
    from app.modules.portfolio.service import held_assets
    from app.modules.watchlists.models import WatchlistAsset

    top = list(
        (
            await db.execute(
                select(Cryptocurrency)
                .where(Cryptocurrency.is_active.is_(True))
                .order_by(Cryptocurrency.market_cap_rank.asc().nulls_last())
                .limit(UNIVERSE_TOP_N)
            )
        ).scalars()
    )
    ids = {c.id for c in top}
    ids |= set((await held_assets(db)).keys())
    ids |= set((await db.execute(select(WatchlistAsset.cryptocurrency_id).distinct())).scalars())
    ids |= {
        i
        for i in (await db.execute(select(Alert.cryptocurrency_id).distinct())).scalars()
        if i is not None
    }
    cryptos = await market.cryptos_by_id(db, list(ids))
    return {k: c for k, c in cryptos.items() if c.symbol.upper() not in STABLECOINS}


async def run(db: AsyncSession, provider: CandleProvider) -> int:
    strategy = await active_strategy(db)
    assets = await universe(db)
    produced = 0
    for timeframe in SCHEDULED_TIMEFRAMES:
        context = await market_context(db, provider, timeframe)
        for crypto in assets.values():
            try:
                await generate(db, crypto, timeframe, provider, strategy, context)
                produced += 1
            except (AppError, ProviderError):
                continue  # asset without a reliable market or provider hiccup: skip
    logger.info("signals_generated", assets=len(assets), signals=produced)
    return produced


# --------------------------------------------------------------------------- read models


async def _to_out(
    db: AsyncSession, signals: Sequence[AnalysisSignal], strategy: SignalStrategy
) -> list[SignalOut]:
    ids = list({s.cryptocurrency_id for s in signals})
    cryptos = await market.cryptos_by_id(db, ids)
    tickers = await market.live_tickers(db, ids)
    out = []
    for s in signals:
        c = cryptos[s.cryptocurrency_id]
        ticker = tickers.get(s.cryptocurrency_id)
        out.append(
            SignalOut(
                id=s.id,
                asset=AssetRef(
                    id=c.id, slug=c.source_id, symbol=c.symbol, name=c.name, image_url=c.image_url
                ),
                timeframe=s.timeframe,
                candle_time=s.candle_time,
                generated_at=s.generated_at,
                reference_price=s.reference_price,
                current_price=ticker.price if ticker else None,
                score=s.score,
                classification=s.classification,
                trend=s.trend,
                components=[
                    ComponentOut(
                        key=comp["key"],
                        label=COMPONENT_LABELS.get(comp["key"], comp["key"]),
                        score=Decimal(comp["score"]),
                        weight_pct=(Decimal(comp["weight"]) * 100).quantize(Decimal("0.1")),
                        detail=comp["detail"],
                    )
                    for comp in s.components
                ],
                justification=s.justification,
                risks=s.risks,
                invalidation=s.invalidation,
                indicators=s.indicators,
                data_source=s.data_source,
                data_fetched_at=s.data_fetched_at,
                data_is_stale=s.data_is_stale,
                strategy_key=strategy.key,
                strategy_version=strategy.version,
                methodology_version=s.methodology_version,
            )
        )
    return out


async def list_latest(
    db: AsyncSession,
    timeframe: Timeframe,
    *,
    classification: str | None,
    only_ids: Sequence[uuid.UUID] | None,
    limit: int,
) -> list[SignalOut]:
    strategy = await active_strategy(db)
    # A signal older than 3 candles no longer describes the market; leave it out.
    fresh_after = utcnow() - timedelta(seconds=TIMEFRAME_SECONDS[timeframe] * 3)
    latest = (
        select(AnalysisSignal)
        .where(
            AnalysisSignal.timeframe == timeframe,
            AnalysisSignal.strategy_id == strategy.id,
            AnalysisSignal.candle_time >= fresh_after,
        )
        .ext(distinct_on(AnalysisSignal.cryptocurrency_id))
        .order_by(AnalysisSignal.cryptocurrency_id, AnalysisSignal.candle_time.desc())
    )
    if only_ids is not None:
        latest = latest.where(AnalysisSignal.cryptocurrency_id.in_(list(only_ids)))
    # Defence in depth: signals stored before a stablecoin was recognised stay hidden.
    latest = latest.join(
        Cryptocurrency, Cryptocurrency.id == AnalysisSignal.cryptocurrency_id
    ).where(func.upper(Cryptocurrency.symbol).not_in(sorted(STABLECOINS)))
    rows = list((await db.execute(latest)).scalars())
    if classification:
        rows = [r for r in rows if r.classification == classification]
    rows.sort(key=lambda r: r.score, reverse=True)
    return await _to_out(db, rows[:limit], strategy)


async def for_asset(
    db: AsyncSession, slug: str, timeframe: Timeframe, provider: CandleProvider
) -> SignalOut:
    crypto = await market.resolve_asset(db, slug)
    if crypto is None or crypto.source_id != slug:
        raise NotFoundError("Ativo não encontrado.")
    strategy = await active_strategy(db)
    signal: AnalysisSignal | None
    try:
        signal = await generate(
            db, crypto, timeframe, provider, strategy, await market_context(db, provider, timeframe)
        )
    except StablecoinError:
        raise
    except (AppError, ProviderError):
        # Provider unavailable: fall back to the most recent stored signal, if any.
        signal = (
            await db.execute(
                select(AnalysisSignal)
                .where(
                    AnalysisSignal.cryptocurrency_id == crypto.id,
                    AnalysisSignal.timeframe == timeframe,
                    AnalysisSignal.strategy_id == strategy.id,
                )
                .order_by(AnalysisSignal.candle_time.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if signal is None:
            raise
    return (await _to_out(db, [signal], strategy))[0]


async def history(
    db: AsyncSession, slug: str, timeframe: Timeframe, limit: int
) -> list[SignalHistoryPoint]:
    crypto = await market.resolve_asset(db, slug)
    if crypto is None or crypto.source_id != slug:
        raise NotFoundError("Ativo não encontrado.")
    strategy = await active_strategy(db)
    rows = list(
        (
            await db.execute(
                select(AnalysisSignal)
                .where(
                    AnalysisSignal.cryptocurrency_id == crypto.id,
                    AnalysisSignal.timeframe == timeframe,
                    AnalysisSignal.strategy_id == strategy.id,
                )
                .order_by(AnalysisSignal.candle_time.desc())
                .limit(limit)
            )
        ).scalars()
    )
    return [
        SignalHistoryPoint(
            candle_time=r.candle_time,
            score=r.score,
            classification=r.classification,
            reference_price=r.reference_price,
        )
        for r in reversed(rows)
    ]


async def latest_classification(
    db: AsyncSession, crypto_id: uuid.UUID, timeframe: str
) -> AnalysisSignal | None:
    strategy = await active_strategy(db)
    return (
        await db.execute(
            select(AnalysisSignal)
            .where(
                AnalysisSignal.cryptocurrency_id == crypto_id,
                AnalysisSignal.timeframe == timeframe,
                AnalysisSignal.strategy_id == strategy.id,
            )
            .order_by(AnalysisSignal.candle_time.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def count(db: AsyncSession) -> int:
    return await db.scalar(select(func.count()).select_from(AnalysisSignal)) or 0
