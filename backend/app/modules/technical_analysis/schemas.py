from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from app.modules.market_data.providers.base import Timeframe


class CandleOut(BaseModel):
    time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    closed: bool


class IndicatorSeries(BaseModel):
    """Aligned 1:1 with `candles`; null during each indicator's warm-up."""

    ema9: list[Decimal | None]
    ema21: list[Decimal | None]
    ema50: list[Decimal | None]
    ema200: list[Decimal | None]
    sma20: list[Decimal | None]
    bb_upper: list[Decimal | None]
    bb_lower: list[Decimal | None]
    rsi: list[Decimal | None]
    macd: list[Decimal | None]
    macd_signal: list[Decimal | None]
    macd_hist: list[Decimal | None]
    volume_sma20: list[Decimal | None]


class LevelOut(BaseModel):
    price: Decimal
    touches: int
    last_touch: datetime
    distance_pct: Decimal


class CriterionOut(BaseModel):
    name: str
    vote: Literal["bullish", "bearish", "neutral"]
    detail: str


class TrendOut(BaseModel):
    classification: Literal["uptrend", "downtrend", "consolidation", "undefined"]
    score: int
    available: int
    confidence: Literal["high", "moderate", "low"]
    summary: str
    criteria: list[CriterionOut]


class Snapshot(BaseModel):
    """Latest values computed on the last *closed* candle (no repainting)."""

    as_of: datetime
    close: Decimal
    rsi: Decimal | None
    rsi_state: Literal["overbought", "oversold", "neutral"] | None
    macd: Decimal | None
    macd_signal: Decimal | None
    macd_hist: Decimal | None
    macd_cross: Literal["bullish", "bearish"] | None
    macd_cross_bars_ago: int | None
    ema9: Decimal | None
    ema21: Decimal | None
    ema50: Decimal | None
    ema200: Decimal | None
    sma20: Decimal | None
    bb_upper: Decimal | None
    bb_lower: Decimal | None
    bb_percent_b: Decimal | None
    bb_bandwidth_pct: Decimal | None
    atr: Decimal | None
    atr_pct: Decimal | None
    volume: Decimal
    volume_ratio: Decimal | None
    volatility_annualized_pct: Decimal | None


class AnalysisOut(BaseModel):
    asset_slug: str
    symbol: str
    timeframe: Timeframe
    source: str
    pair: str
    quote: Literal["USDT"]
    fetched_at: datetime
    is_stale: bool
    candles: list[CandleOut]
    indicators: IndicatorSeries
    snapshot: Snapshot | None
    trend: TrendOut
    supports: list[LevelOut]
    resistances: list[LevelOut]
    methodology_version: str
