from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from app.modules.market_data.providers.base import Timeframe
from app.modules.portfolio.schemas import AssetRef

SignalClass = Literal["buy_potential", "neutral", "attention", "sell_potential"]

COMPONENT_LABELS = {
    "trend": "Tendência",
    "momentum": "Momentum",
    "volume": "Volume",
    "volatility": "Volatilidade",
    "levels": "Suportes e resistências",
    "market": "Condições de mercado",
}


class ComponentOut(BaseModel):
    key: str
    label: str
    score: Decimal
    weight_pct: Decimal
    detail: str


class StrategyOut(BaseModel):
    key: str
    version: int
    name: str
    weights_pct: dict[str, Decimal]
    buy_threshold: Decimal
    sell_threshold: Decimal


class SignalOut(BaseModel):
    id: int
    asset: AssetRef
    timeframe: Timeframe
    candle_time: datetime
    generated_at: datetime
    reference_price: Decimal
    current_price: Decimal | None
    score: Decimal
    classification: SignalClass
    trend: str
    components: list[ComponentOut]
    justification: str
    risks: list[str]
    invalidation: list[str]
    indicators: dict[str, object]
    data_source: str
    data_fetched_at: datetime
    data_is_stale: bool
    strategy_key: str
    strategy_version: int
    methodology_version: str


class SignalListOut(BaseModel):
    items: list[SignalOut]
    timeframe: Timeframe
    strategy: StrategyOut
    disclaimer: str


class SignalHistoryPoint(BaseModel):
    candle_time: datetime
    score: Decimal
    classification: SignalClass
    reference_price: Decimal
