import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.modules.portfolio.engine import PRICED_TYPES, TxType

Currency = Literal["BRL", "USD"]
PositiveQty = Annotated[Decimal, Field(gt=0, max_digits=38, decimal_places=18)]
NonNegative = Annotated[Decimal, Field(ge=0, max_digits=38, decimal_places=18)]

#: Types that may carry a fee withheld in the asset itself.
FEE_QUANTITY_TYPES = frozenset({TxType.BUY, TxType.TRANSFER, TxType.WITHDRAWAL})


class AssetRef(BaseModel):
    id: uuid.UUID
    slug: str
    symbol: str
    name: str
    image_url: str | None


class ExchangeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    kind: str


class PortfolioOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    created_at: datetime


class TransactionIn(BaseModel):
    type: TxType
    asset_id: uuid.UUID
    quantity: PositiveQty
    unit_price: NonNegative | None = None
    quote_currency: Currency = "BRL"
    fee_amount: NonNegative = Decimal(0)
    fee_quantity: NonNegative = Decimal(0)
    to_asset_id: uuid.UUID | None = None
    to_quantity: PositiveQty | None = None
    executed_at: datetime
    exchange_id: str | None = Field(default=None, max_length=32)
    to_exchange_id: str | None = Field(default=None, max_length=32)
    notes: str | None = Field(default=None, max_length=1000)

    @field_validator("executed_at")
    @classmethod
    def _aware_and_not_future(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Informe a data com fuso horário.")
        if value > datetime.now(UTC) + timedelta(minutes=5):
            raise ValueError("A data não pode estar no futuro.")
        if value.year < 2009:
            raise ValueError("Data anterior à existência de criptomoedas.")
        return value.astimezone(UTC)

    @field_validator("notes")
    @classmethod
    def _strip_notes(cls, value: str | None) -> str | None:
        return value.strip() or None if value else None

    @model_validator(mode="after")
    def _rules_per_type(self) -> Self:
        if self.type in PRICED_TYPES and self.unit_price is None:
            raise ValueError("Informe o preço unitário.")
        if self.type == TxType.CONVERSION:
            if self.to_asset_id is None or self.to_quantity is None:
                raise ValueError("Informe o ativo e a quantidade recebidos na conversão.")
            if self.to_asset_id == self.asset_id:
                raise ValueError("A conversão deve ser entre ativos diferentes.")
        elif self.to_asset_id is not None or self.to_quantity is not None:
            raise ValueError("Ativo de destino só se aplica a conversões.")
        if self.fee_quantity and self.type not in FEE_QUANTITY_TYPES:
            raise ValueError(
                "Taxa no próprio ativo só se aplica a compras, transferências e retiradas."
            )
        # Value-free movements: a price would be ignored, so reject it to avoid confusion.
        if self.type in (TxType.TRANSFER, TxType.FEE) and (
            self.unit_price is not None or self.fee_amount
        ):
            raise ValueError("Transferências e taxas não têm preço; use a taxa no próprio ativo.")
        if self.type != TxType.TRANSFER and self.to_exchange_id:
            raise ValueError("Destino só se aplica a transferências.")
        return self


class TransactionOut(BaseModel):
    id: uuid.UUID
    type: TxType
    asset: AssetRef
    quantity: Decimal
    unit_price: Decimal | None
    quote_currency: Currency
    gross_amount: Decimal | None
    fee_amount: Decimal
    fee_quantity: Decimal
    to_asset: AssetRef | None
    to_quantity: Decimal | None
    fx_usd_brl: Decimal
    executed_at: datetime
    exchange_id: str | None
    to_exchange_id: str | None
    notes: str | None
    source: str
    created_at: datetime


class TransactionListOut(BaseModel):
    items: list[TransactionOut]
    total: int
    page: int
    page_size: int


class PriceStatus(BaseModel):
    fetched_at: datetime | None
    is_stale: bool
    missing_assets: list[str] = Field(description="Assets valued at their last trade price")


class PositionOut(BaseModel):
    asset: AssetRef
    quantity: Decimal
    price: Decimal | None
    market_value: Decimal
    cost_basis: Decimal
    average_cost: Decimal | None
    unrealized_pnl: Decimal
    unrealized_pct: Decimal | None
    realized_pnl: Decimal
    fees: Decimal
    change_pct_24h: Decimal | None
    weight_pct: Decimal
    price_estimated: bool


class Change24hOut(BaseModel):
    value_change: Decimal
    market_effect: Decimal
    net_flows: Decimal
    pct: Decimal | None


class SummaryOut(BaseModel):
    portfolio: PortfolioOut
    currency: Currency
    market_value: Decimal
    market_value_usd: Decimal
    market_value_brl: Decimal
    cost_basis: Decimal
    unrealized_pnl: Decimal
    realized_pnl: Decimal
    total_pnl: Decimal
    total_inflows: Decimal
    total_outflows: Decimal
    net_invested: Decimal
    fees: Decimal
    change_24h: Change24hOut
    positions: list[PositionOut]
    closed_positions: list[PositionOut]
    transaction_count: int
    fx_usd_brl: Decimal | None
    prices: PriceStatus
    as_of: datetime


class SeriesPoint(BaseModel):
    day: date
    value: Decimal
    net_invested: Decimal
    flow: Decimal
    twr_pct: Decimal
    btc_pct: Decimal | None
    eth_pct: Decimal | None
    estimated: bool


class ReturnsOut(BaseModel):
    """Time-weighted returns in percent; null when the portfolio is younger than the period."""

    d1: Decimal | None
    d7: Decimal | None
    d30: Decimal | None
    d90: Decimal | None
    y1: Decimal | None
    inception: Decimal | None


class PerformanceOut(BaseModel):
    currency: Currency
    inception_date: date | None
    history_start: date | None
    #: false when the oldest transactions predate the price history available (365 days)
    #: or some daily prices are still being fetched.
    history_complete: bool
    series: list[SeriesPoint]
    returns: ReturnsOut
    xirr_pct: Decimal | None
    xirr_applicable: bool
    as_of: datetime


class InsightOut(BaseModel):
    id: str
    severity: Literal["info", "attention", "risk"]
    title: str
    message: str
    basis: str = Field(description="How the figure was computed")


class InsightsOut(BaseModel):
    items: list[InsightOut]
    as_of: datetime


class CsvIn(BaseModel):
    content: str = Field(min_length=1, max_length=1_000_000)
    skip_invalid: bool = False


class CsvRowOut(BaseModel):
    line: int
    status: Literal["valid", "error", "duplicate"]
    errors: list[str]
    type: str | None = None
    asset: str | None = None
    quantity: str | None = None
    unit_price: str | None = None
    quote_currency: str | None = None
    executed_at: datetime | None = None


class CsvPreviewOut(BaseModel):
    rows: list[CsvRowOut]
    valid: int
    errors: int
    duplicates: int


class CsvCommitOut(BaseModel):
    imported: int
    skipped: int
