import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

QuoteCurrency = Literal["USD", "BRL"]
SortKey = Literal["rank", "market_cap", "price", "change_24h", "change_7d", "volume", "name"]


class DataStatus(BaseModel):
    """Freshness metadata attached to every market response."""

    source: str
    attribution: str
    fetched_at: datetime | None
    is_stale: bool
    stale_after_seconds: int
    # Percent changes are computed by the provider in USD, also when values are shown in BRL.
    change_basis: Literal["USD"] = "USD"
    currency: QuoteCurrency
    fx_rate: Decimal | None = None
    fx_observed_at: datetime | None = None


class AssetBriefOut(BaseModel):
    id: uuid.UUID
    slug: str
    symbol: str
    name: str
    image_url: str | None


class AssetOut(BaseModel):
    id: uuid.UUID
    slug: str
    symbol: str
    name: str
    image_url: str | None
    market_cap_rank: int | None
    price: Decimal
    market_cap: Decimal | None
    fully_diluted_valuation: Decimal | None
    total_volume: Decimal | None
    high_24h: Decimal | None
    low_24h: Decimal | None
    change_pct_1h: Decimal | None
    change_pct_24h: Decimal | None
    change_pct_7d: Decimal | None
    circulating_supply: Decimal | None
    total_supply: Decimal | None
    max_supply: Decimal | None
    ath: Decimal | None
    ath_change_pct: Decimal | None
    ath_date: datetime | None
    source_updated_at: datetime


class AssetListOut(BaseModel):
    items: list[AssetOut]
    total: int
    page: int
    page_size: int
    status: DataStatus


class AssetDetailOut(BaseModel):
    asset: AssetOut
    status: DataStatus


class MarketOverviewOut(BaseModel):
    """Aggregates over the tracked universe (top-N by market cap), not the whole market."""

    tracked_assets: int
    total_market_cap: Decimal | None
    total_volume_24h: Decimal | None
    btc_dominance_pct: Decimal | None
    advancers_24h: int
    decliners_24h: int
    top_gainers: list[AssetOut]
    top_losers: list[AssetOut]
    status: DataStatus


Market = Literal["CRYPTO", "B3", "US"]


class MarketOut(BaseModel):
    """An enabled market with its session state and data terms."""

    market: Market
    label: str
    currency: str
    state: Literal["open", "closed", "always_open"]
    last_close: datetime | None
    next_open: datetime | None
    #: provider delay in seconds; 0 means real time
    delay_seconds: int
    attribution: str
    last_sync_at: datetime | None


class InstrumentHitOut(BaseModel):
    id: uuid.UUID
    market: Market
    asset_type: str
    exchange: str | None
    symbol: str
    slug: str
    name: str
    image_url: str | None
    currency: str
    price: Decimal | None
    change_pct: Decimal | None
    delay_seconds: int | None
    #: when the quote data was current (not when it was fetched)
    as_of: datetime | None


class ExchangeStatusOut(BaseModel):
    """Session state and data terms attached to every exchange-market response."""

    market: Market
    currency: str
    state: Literal["open", "closed", "always_open"]
    last_close: datetime | None
    next_open: datetime | None
    #: provider delay in seconds; never 0 on the supported plans, so never "real time"
    delay_seconds: int
    #: when the newest quote's data was current (not when it was fetched)
    as_of: datetime | None
    fetched_at: datetime | None
    is_stale: bool
    attribution: str


class ExchangeAssetOut(BaseModel):
    id: uuid.UUID
    symbol: str
    name: str
    asset_type: str
    exchange: str | None
    sector: str | None
    image_url: str | None
    currency: str
    price: Decimal
    #: change against the previous session close
    change_pct: Decimal | None
    volume: Decimal | None
    #: price x volume, in the instrument's currency
    traded_value: Decimal | None
    market_cap: Decimal | None


class ExchangeAssetListOut(BaseModel):
    items: list[ExchangeAssetOut]
    total: int
    page: int
    page_size: int
    status: ExchangeStatusOut


class ExchangeOverviewOut(BaseModel):
    status: ExchangeStatusOut
    #: ETF that tracks the main index, shown as a labeled proxy: index values are licensed
    reference: ExchangeAssetOut | None
    counts: dict[str, int]
    advancers: int
    decliners: int
    top_gainers: list[ExchangeAssetOut]
    top_losers: list[ExchangeAssetOut]
    most_traded: list[ExchangeAssetOut]


UnavailableReason = Literal[
    "token_required",
    "plan_required",
    "no_data",
    "rate_limited",
    "quota_reached",
    "provider_unavailable",
]


class ExchangeDetailOut(BaseModel):
    asset: ExchangeAssetOut
    open: Decimal | None
    day_high: Decimal | None
    day_low: Decimal | None
    previous_close: Decimal | None
    week52_low: Decimal | None
    week52_high: Decimal | None
    #: why the session figures above are missing, if they are
    detail_unavailable: UnavailableReason | None
    status: ExchangeStatusOut


class DailyBarOut(BaseModel):
    day: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal | None


class ExchangeHistoryOut(BaseModel):
    symbol: str
    range: str
    #: depth the current data plan allows
    allowed_ranges: list[str]
    bars: list[DailyBarOut]
    unavailable: UnavailableReason | None
