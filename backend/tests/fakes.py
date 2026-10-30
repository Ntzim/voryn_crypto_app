"""In-memory market data providers for tests."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from app.modules.market_data.providers.base import (
    Candle,
    DailyClose,
    FxQuote,
    MarketQuote,
    ProviderError,
    Timeframe,
)
from app.modules.market_data.providers.binance import UnknownPairError

NOW = datetime.now(UTC).replace(microsecond=0)


def quote(
    source_id: str,
    symbol: str,
    rank: int,
    price: str,
    change: str = "0",
    cap: str = "1000",
) -> MarketQuote:
    return MarketQuote(
        source_id=source_id,
        symbol=symbol,
        name=source_id.title(),
        image_url=None,
        market_cap_rank=rank,
        quote_currency="USD",
        price=Decimal(price),
        market_cap=Decimal(cap),
        fully_diluted_valuation=None,
        total_volume=Decimal("1000"),
        high_24h=None,
        low_24h=None,
        change_pct_1h=None,
        change_pct_24h=Decimal(change),
        change_pct_7d=None,
        circulating_supply=None,
        total_supply=None,
        max_supply=None,
        ath=Decimal(price) * 2,
        ath_change_pct=Decimal("-50"),
        ath_date=None,
        source_updated_at=NOW,
    )


class FakeProvider:
    name = "coingecko"

    def __init__(
        self,
        quotes: list[MarketQuote],
        rate: str = "5.25",
        extra: list[MarketQuote] | None = None,
        closes: dict[str, list[DailyClose]] | None = None,
    ) -> None:
        self.quotes = quotes
        self.extra = extra or []
        self.rate = Decimal(rate)
        self.closes = closes or {}
        self.history_calls: list[str] = []

    async def fetch_top_markets(self, vs_currency: str, limit: int) -> list[MarketQuote]:
        return self.quotes[:limit]

    async def fetch_markets_by_ids(
        self, vs_currency: str, source_ids: list[str]
    ) -> list[MarketQuote]:
        return [q for q in self.extra if q.source_id in source_ids]

    async def fetch_daily_closes(self, source_id: str, days: int) -> list[DailyClose]:
        self.history_calls.append(source_id)
        return self.closes.get(source_id, [])

    async def fetch_fx_rate(self, base: str, quote: str) -> FxQuote:
        return FxQuote(base, quote, self.rate, NOW)


class FakeFxHistory:
    """Official-rate stand-in: a fixed USD→BRL observation for every requested day."""

    name = "bcb_ptax"

    def __init__(self, rates: dict[date, Decimal] | None = None) -> None:
        self.rates = rates or {}
        self.calls = 0

    async def aclose(self) -> None:
        return None

    async def fetch_usd_brl(self, start: date, end: date) -> list[FxQuote]:
        self.calls += 1
        return [
            FxQuote("USD", "BRL", rate, datetime(d.year, d.month, d.day, 12, tzinfo=UTC))
            for d, rate in sorted(self.rates.items())
            if start <= d <= end
        ]


def shifted(q: MarketQuote, **changes: object) -> MarketQuote:
    return replace(q, **changes)  # type: ignore[arg-type]


CANDLE_NOW = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)


def daily_candles(n: int, last_close: Decimal, live: bool = True) -> list[Candle]:
    start = CANDLE_NOW - timedelta(days=n)
    out = []
    for i in range(n):
        close = last_close * (Decimal(1) + Decimal(i - n + 1) / 1000)
        out.append(
            Candle(
                start + timedelta(days=i),
                close,
                close * Decimal("1.01"),
                close * Decimal("0.99"),
                close,
                Decimal(10),
                Decimal(10) * close,
                True,
            )
        )
    if live:
        out.append(
            Candle(
                CANDLE_NOW,
                last_close,
                last_close,
                last_close,
                last_close,
                Decimal(1),
                last_close,
                False,
            )
        )
    return out


class FakeCandles:
    name = "binance"

    def __init__(self, data: dict[str, list[Candle]] | None = None, fail: bool = False) -> None:
        self.data = data or {}
        self.fail = fail
        self.calls = 0

    def pair_for(self, symbol: str) -> str | None:
        return None if symbol == "USDT" else f"{symbol}USDT"

    async def aclose(self) -> None:
        return None

    async def fetch_candles(self, pair: str, timeframe: Timeframe, limit: int) -> list[Candle]:
        self.calls += 1
        if self.fail:
            raise ProviderError("down")
        if pair not in self.data:
            raise UnknownPairError(pair)
        return self.data[pair]
