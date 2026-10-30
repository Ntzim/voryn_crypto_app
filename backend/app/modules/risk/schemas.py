import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from app.modules.portfolio.schemas import AssetRef, Currency
from app.modules.risk.scenario import Method

#: days of daily history (the UI offers 90, 180 and 365)
RiskWindow = Annotated[int, Field(ge=30, le=365)]
Severity = Literal["info", "attention", "risk"]
Liquidity = Literal["high", "medium", "low", "unknown"]


class DrawdownOut(BaseModel):
    pct: Decimal | None
    peak: date | None
    trough: date | None
    current_pct: Decimal | None


class StressWindowOut(BaseModel):
    days: int
    pct: Decimal
    start: date
    end: date
    #: the change applied to today's covered value, in the reporting currency
    amount: Decimal


class VarOut(BaseModel):
    confidence_pct: Decimal
    pct: Decimal | None
    amount: Decimal | None


class ConcentrationOut(BaseModel):
    hhi: Decimal
    effective_assets: Decimal
    top1_pct: Decimal
    top3_pct: Decimal
    stablecoin_pct: Decimal


class AssetRiskOut(BaseModel):
    asset: AssetRef
    weight_pct: Decimal
    market_value: Decimal
    is_stablecoin: bool
    covered: bool
    observations: int
    volatility_pct: Decimal | None
    max_drawdown_pct: Decimal | None
    beta_btc: Decimal | None
    var95_pct: Decimal | None
    risk_contribution_pct: Decimal | None
    avg_daily_volume_usd: Decimal | None
    position_to_volume_pct: Decimal | None
    liquidity: Liquidity


class CorrelationOut(BaseModel):
    symbols: list[str]
    values: list[list[Decimal | None]]


class RiskFlagOut(BaseModel):
    id: str
    severity: Severity
    title: str
    message: str
    basis: str


class RiskOut(BaseModel):
    currency: Currency
    window_days: RiskWindow
    period_start: date | None
    period_end: date | None
    observations: int
    market_value: Decimal
    covered_value: Decimal
    coverage_pct: Decimal
    uncovered_assets: list[str]
    volatility_pct: Decimal | None
    drawdown: DrawdownOut
    var: list[VarOut]
    expected_shortfall_95: VarOut
    beta_btc: Decimal | None
    worst_day: StressWindowOut | None
    stress: list[StressWindowOut]
    concentration: ConcentrationOut
    assets: list[AssetRiskOut]
    correlation: CorrelationOut
    flags: list[RiskFlagOut]
    data_source: str
    methodology: list[str]
    as_of: datetime


class ScenarioOverride(BaseModel):
    asset_id: uuid.UUID
    change_pct: Decimal = Field(ge=-100, le=1000)


class ScenarioIn(BaseModel):
    btc_change_pct: Decimal = Field(ge=-100, le=1000)
    overrides: list[ScenarioOverride] = Field(default_factory=list, max_length=100)
    window: RiskWindow = 365


class ScenarioLineOut(BaseModel):
    asset: AssetRef
    market_value: Decimal
    change_pct: Decimal
    method: Method
    new_value: Decimal
    pnl: Decimal


class ScenarioOut(BaseModel):
    currency: Currency
    btc_change_pct: Decimal
    market_value: Decimal
    new_value: Decimal
    pnl: Decimal
    pnl_pct: Decimal | None
    lines: list[ScenarioLineOut]
    notes: list[str]
    as_of: datetime
