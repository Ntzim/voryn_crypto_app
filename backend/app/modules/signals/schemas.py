from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from app.modules.market_data.providers.base import Timeframe
from app.modules.market_data.schemas import ExchangeStatusOut
from app.modules.portfolio.schemas import AssetRef
from app.modules.signals.quality import DataQuality

SignalClass = Literal["buy_potential", "neutral", "attention", "sell_potential"]

COMPONENT_LABELS = {
    "trend": "Tendência",
    "momentum": "Momentum",
    "volume": "Volume",
    "volatility": "Volatilidade",
    "levels": "Suportes e resistências",
    "market": "Condições de mercado",
    "valuation": "Preço sobre patrimônio (P/VP)",
    "income": "Rendimentos",
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
    #: signals.quality grade; anything but "valid" means buy/sell was withheld or the
    #: signal is historical (is_current false) and must not be shown as today's view
    data_quality: DataQuality
    quality_reasons: list[str]
    is_current: bool
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


class FiiFundamentalsOut(BaseModel):
    price_to_nav: Decimal | None
    nav_per_share: Decimal | None
    nav_as_of: str | None
    #: percent, on today's price
    dividend_yield_12m: Decimal | None
    months_paid_12m: int | None
    last_payment_rate: Decimal | None
    last_payment_date: str | None
    segment: str | None


class B3SignalOut(SignalOut):
    asset_type: str
    sector: str | None
    currency: str
    fundamentals: FiiFundamentalsOut | None
    #: what this analysis covers and what it leaves out
    scope: str


class B3SignalListOut(BaseModel):
    items: list[B3SignalOut]
    asset_type: str
    strategy: StrategyOut
    disclaimer: str
    scope: str
    status: ExchangeStatusOut
