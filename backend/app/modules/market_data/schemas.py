import uuid
from datetime import datetime
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
