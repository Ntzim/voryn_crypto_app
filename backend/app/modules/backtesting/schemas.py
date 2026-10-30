import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from app.modules.portfolio.schemas import AssetRef

StrategyKey = Literal["voryn_signal", "ema_cross", "macd_cross", "rsi_reversion", "buy_and_hold"]
BacktestTimeframe = Literal["1d", "4h"]
RunStatus = Literal["queued", "running", "done", "failed"]
Segment = Literal["train", "validation"]


class BacktestIn(BaseModel):
    asset_id: uuid.UUID
    timeframe: BacktestTimeframe = "1d"
    strategy: StrategyKey
    params: dict[str, int] = Field(default_factory=dict, max_length=4)
    optimize: bool = False
    fee_bps: Decimal = Field(default=Decimal(10), ge=0, le=100)
    slippage_bps: Decimal = Field(default=Decimal(5), ge=0, le=100)
    train_pct: int = Field(default=70, ge=50, le=90)


class ParamSpecOut(BaseModel):
    key: str
    label: str
    default: int
    min: int
    max: int
    grid: list[int]


class StrategyInfoOut(BaseModel):
    key: StrategyKey
    label: str
    description: str
    params: list[ParamSpecOut]
    optimizable: bool


class MetricsOut(BaseModel):
    start: datetime | None
    end: datetime | None
    bars: int
    final_equity: Decimal
    total_return_pct: Decimal
    cagr_pct: Decimal | None
    max_drawdown_pct: Decimal
    volatility_pct: Decimal | None
    sharpe: Decimal | None
    trades: int
    win_rate_pct: Decimal | None
    avg_trade_pct: Decimal | None
    profit_factor: Decimal | None
    exposure_pct: Decimal
    fees: Decimal


class SegmentOut(BaseModel):
    strategy: MetricsOut
    benchmark: MetricsOut


class GridRowOut(BaseModel):
    params: dict[str, int | str]
    train_sharpe: Decimal | None
    train_return_pct: Decimal
    selected: bool


class EquityPointOut(BaseModel):
    time: datetime
    segment: Segment
    strategy: Decimal
    benchmark: Decimal


class TradeOut(BaseModel):
    segment: Segment
    entry_time: datetime
    entry_price: Decimal
    exit_time: datetime | None
    exit_price: Decimal | None
    return_pct: Decimal | None


class BacktestResultOut(BaseModel):
    selected_params: dict[str, int | str]
    grid: list[GridRowOut]
    train: SegmentOut
    validation: SegmentOut
    equity: list[EquityPointOut]
    trades: list[TradeOut]
    initial_capital: Decimal
    quote: str
    candles: int
    warmup: int
    first_candle: datetime
    last_candle: datetime
    split_at: datetime
    data_source: str
    data_fetched_at: datetime
    notes: list[str]


class BacktestSummaryOut(BaseModel):
    id: uuid.UUID
    asset: AssetRef
    timeframe: BacktestTimeframe
    strategy: StrategyKey
    status: RunStatus
    validation_return_pct: Decimal | None
    benchmark_return_pct: Decimal | None
    created_at: datetime
    finished_at: datetime | None


class BacktestOut(BacktestSummaryOut):
    params: dict[str, int]
    optimize: bool
    fee_bps: Decimal
    slippage_bps: Decimal
    train_pct: int
    engine_version: str
    error: str | None
    result: BacktestResultOut | None
