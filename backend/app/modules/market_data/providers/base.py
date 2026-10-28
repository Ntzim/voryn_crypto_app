"""Provider-agnostic market data contracts.

Business logic depends only on these types, so CoinGecko can be swapped or complemented
(CoinMarketCap, Kaiko, exchange feeds) without touching services or the API.
"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Protocol


class ProviderError(Exception):
    """Upstream unavailable, rate limited or returned unusable data."""


@dataclass(frozen=True, slots=True)
class MarketQuote:
    source_id: str
    symbol: str
    name: str
    image_url: str | None
    market_cap_rank: int | None
    quote_currency: str
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


@dataclass(frozen=True, slots=True)
class FxQuote:
    base_currency: str
    quote_currency: str
    rate: Decimal
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class DailyClose:
    day: date
    close: Decimal


Timeframe = Literal["15m", "1h", "4h", "1d", "1w"]

TIMEFRAME_SECONDS: dict[str, int] = {
    "15m": 15 * 60,
    "1h": 3600,
    "4h": 4 * 3600,
    "1d": 86400,
    "1w": 7 * 86400,
}


@dataclass(frozen=True, slots=True)
class Candle:
    open_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    #: volume in units of the base asset
    volume: Decimal
    #: volume in the quote currency (USDT)
    quote_volume: Decimal
    closed: bool


class CandleProvider(Protocol):
    name: str

    def pair_for(self, symbol: str) -> str | None: ...

    async def fetch_candles(self, pair: str, timeframe: Timeframe, limit: int) -> list[Candle]: ...


class MarketDataProvider(Protocol):
    name: str

    async def fetch_top_markets(self, vs_currency: str, limit: int) -> list[MarketQuote]: ...

    async def fetch_markets_by_ids(
        self, vs_currency: str, source_ids: list[str]
    ) -> list[MarketQuote]: ...

    async def fetch_daily_closes(self, source_id: str, days: int) -> list[DailyClose]: ...

    async def fetch_fx_rate(self, base: str, quote: str) -> FxQuote: ...


class FxHistoryProvider(Protocol):
    """Official historical USD→BRL observations (one per business day)."""

    name: str

    async def fetch_usd_brl(self, start: date, end: date) -> list[FxQuote]: ...
