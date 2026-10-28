"""Technical analysis use-case: candles → indicators, snapshot, trend and levels."""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal, localcontext
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.modules.market_data import candles as candle_service
from app.modules.market_data import service as market
from app.modules.market_data.providers.base import Candle, CandleProvider, Timeframe
from app.modules.technical_analysis import indicators as ind
from app.modules.technical_analysis.levels import Level, detect_levels
from app.modules.technical_analysis.schemas import (
    AnalysisOut,
    CandleOut,
    CriterionOut,
    IndicatorSeries,
    LevelOut,
    Snapshot,
    TrendOut,
)
from app.modules.technical_analysis.trend import TrendInputs, TrendResult, classify

#: Bumped whenever an indicator, threshold or rule changes (signals will record it).
METHODOLOGY_VERSION = "ta-1.0"
PERIODS_PER_YEAR = {"15m": 35040, "1h": 8760, "4h": 2190, "1d": 365, "1w": 52}
VOLATILITY_WINDOW = 30
MACD_CROSS_LOOKBACK = 3


def sig(value: Decimal | None) -> Decimal | None:
    """Round to 12 significant digits for transport (works for BTC and micro-caps alike)."""
    if value is None:
        return None
    with localcontext() as ctx:
        ctx.prec = 12
        return +value


def _round(series: ind.Series) -> list[Decimal | None]:
    return [sig(v) for v in series]


def _last(series: ind.Series) -> Decimal | None:
    return series[-1] if series else None


def _percentile_rank(values: Sequence[Decimal], current: Decimal) -> Decimal:
    return Decimal(sum(1 for v in values if v <= current)) / len(values) * 100


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    series: IndicatorSeries
    snapshot: Snapshot | None
    trend: TrendResult | None
    supports: list[Level]
    resistances: list[Level]


def analyze(candles: Sequence[Candle], timeframe: Timeframe) -> AnalysisResult:
    """Pure computation over candles; indicators use closed candles only."""
    closed = [c for c in candles if c.closed]
    live = len(candles) - len(closed)
    closes = [c.close for c in closed]
    highs = [c.high for c in closed]
    lows = [c.low for c in closed]
    volumes = [c.volume for c in closed]

    ema9, ema21, ema50, ema200 = (ind.ema(closes, n) for n in (9, 21, 50, 200))
    sma20 = ind.sma(closes, 20)
    bb_upper, _bb_mid, bb_lower = ind.bollinger(closes, 20)
    rsi = ind.rsi(closes, 14)
    macd_line, macd_signal, macd_hist = ind.macd(closes)
    atr = ind.atr(highs, lows, closes, 14)
    volume_sma = ind.sma(volumes, 20)

    pad: list[Decimal | None] = [None] * live
    series = IndicatorSeries(
        ema9=_round(ema9) + pad,
        ema21=_round(ema21) + pad,
        ema50=_round(ema50) + pad,
        ema200=_round(ema200) + pad,
        sma20=_round(sma20) + pad,
        bb_upper=_round(bb_upper) + pad,
        bb_lower=_round(bb_lower) + pad,
        rsi=_round(rsi) + pad,
        macd=_round(macd_line) + pad,
        macd_signal=_round(macd_signal) + pad,
        macd_hist=_round(macd_hist) + pad,
        volume_sma20=_round(volume_sma) + pad,
    )

    snapshot: Snapshot | None = None
    trend_inputs: TrendInputs | None = None
    levels: tuple[list[Level], list[Level]] = ([], [])
    if closed:
        last = closed[-1]
        close = last.close
        atr_now = _last(atr)
        atr_pct = atr_now / close * 100 if atr_now is not None else None

        bandwidths = [
            (u - lo) / m * 100
            for u, lo, m in zip(bb_upper[-100:], bb_lower[-100:], sma20[-100:], strict=True)
            if u is not None and lo is not None and m
        ]
        bandwidth = bandwidths[-1] if bandwidths else None
        upper, lower = _last(bb_upper), _last(bb_lower)
        percent_b = (
            (close - lower) / (upper - lower)
            if upper is not None and lower is not None and upper != lower
            else None
        )

        cross: Literal["bullish", "bearish"] | None = None
        cross_ago: int | None = None
        hist = [h for h in macd_hist[-(MACD_CROSS_LOOKBACK + 1) :] if h is not None]
        for i in range(len(hist) - 1, 0, -1):
            if (hist[i] > 0) != (hist[i - 1] > 0):
                cross = "bullish" if hist[i] > 0 else "bearish"
                cross_ago = len(hist) - 1 - i
                break

        rsi_now = _last(rsi)
        vol_avg = _last(volume_sma)
        vol = ind.historical_volatility(closes, VOLATILITY_WINDOW, PERIODS_PER_YEAR[timeframe])
        snapshot = Snapshot(
            as_of=last.open_time,
            close=close,
            rsi=sig(rsi_now),
            rsi_state=None
            if rsi_now is None
            else "overbought"
            if rsi_now >= 70
            else "oversold"
            if rsi_now <= 30
            else "neutral",
            macd=sig(_last(macd_line)),
            macd_signal=sig(_last(macd_signal)),
            macd_hist=sig(_last(macd_hist)),
            macd_cross=cross,
            macd_cross_bars_ago=cross_ago,
            ema9=sig(_last(ema9)),
            ema21=sig(_last(ema21)),
            ema50=sig(_last(ema50)),
            ema200=sig(_last(ema200)),
            sma20=sig(_last(sma20)),
            bb_upper=sig(upper),
            bb_lower=sig(lower),
            bb_percent_b=sig(percent_b),
            bb_bandwidth_pct=sig(bandwidth),
            atr=sig(atr_now),
            atr_pct=sig(atr_pct),
            volume=last.volume,
            volume_ratio=sig(last.volume / vol_avg) if vol_avg else None,
            volatility_annualized_pct=sig(vol * 100) if vol is not None else None,
        )
        trend_inputs = TrendInputs(
            closed_candles=len(closed),
            close=close,
            ema21=_last(ema21),
            ema50=_last(ema50),
            ema50_prev=ema50[-11] if len(ema50) > 10 else None,
            ema200=_last(ema200),
            macd=_last(macd_line),
            macd_signal=_last(macd_signal),
            rsi=rsi_now,
            atr_pct=atr_pct,
            bandwidth_percentile=_percentile_rank(bandwidths, bandwidth)
            if bandwidth is not None
            else None,
        )
        levels = detect_levels(closed, atr_now)

    trend = classify(trend_inputs) if trend_inputs else None
    return AnalysisResult(series, snapshot, trend, levels[0], levels[1])


def _level_out(level: Level, price: Decimal) -> LevelOut:
    return LevelOut(
        price=sig(level.price) or level.price,
        touches=level.touches,
        last_touch=level.last_touch,
        distance_pct=sig((level.price / price - 1) * 100) or Decimal(0),
    )


async def asset_analysis(
    db: AsyncSession, slug: str, timeframe: Timeframe, provider: CandleProvider
) -> AnalysisOut:
    crypto = await market.resolve_asset(db, slug)
    if crypto is None or crypto.source_id != slug:
        raise NotFoundError("Ativo não encontrado.")
    candle_set = await candle_service.get_candles(db, crypto, timeframe, provider)
    result = analyze(candle_set.candles, timeframe)
    trend = result.trend
    price = candle_set.candles[-1].close
    return AnalysisOut(
        asset_slug=crypto.source_id,
        symbol=crypto.symbol,
        timeframe=timeframe,
        source=candle_set.source,
        pair=candle_set.pair,
        quote="USDT",
        fetched_at=candle_set.fetched_at,
        is_stale=candle_set.is_stale,
        candles=[
            CandleOut(
                time=c.open_time,
                open=c.open,
                high=c.high,
                low=c.low,
                close=c.close,
                volume=c.volume,
                closed=c.closed,
            )
            for c in candle_set.candles
        ],
        indicators=result.series,
        snapshot=result.snapshot,
        trend=TrendOut(
            classification=trend.classification,
            score=trend.score,
            available=trend.available,
            confidence=trend.confidence,
            summary=trend.summary,
            criteria=[
                CriterionOut(name=c.name, vote=c.vote, detail=c.detail) for c in trend.criteria
            ],
        )
        if trend
        else TrendOut(
            classification="undefined",
            score=0,
            available=0,
            confidence="low",
            summary="Sem candles fechados para analisar.",
            criteria=[],
        ),
        supports=[_level_out(lv, price) for lv in result.supports],
        resistances=[_level_out(lv, price) for lv in result.resistances],
        methodology_version=METHODOLOGY_VERSION,
    )
