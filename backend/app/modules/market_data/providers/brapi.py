"""brapi.dev adapter for B3 (https://brapi.dev/docs).

- The catalogue endpoint (`/v2/tickers`) returns every listed instrument with its latest
  quote, ~1000 per page, so one sync costs a handful of requests (free plan: 15k/month).
- Quotes are delayed by plan (free 30 min, startup 15 min, pro 5 min); the delay is
  declared with every quote so nothing downstream presents it as real time.
- brapi is not a licensed B3 market data distributor: production display of B3 quotes
  stays behind `MARKETS_ENABLED` until licensing is settled (docs/MULTIMARKET_PLAN.md).
- JSON numbers are parsed as Decimal; malformed rows are dropped, never stored.
- 5xx/timeouts are retried with exponential backoff; a 429 waits for Retry-After; 400, 401,
  403 and 404 are final (https://brapi.dev/docs/troubleshooting).
"""

import asyncio
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.config import get_settings
from app.core.logging import get_logger
from app.modules.market_data.providers.base import ProviderError

logger = get_logger(__name__)

SOURCE = "brapi"
ATTRIBUTION = "Dados de mercado B3 fornecidos por brapi.dev"
DELAY_SECONDS = {"free": 1800, "startup": 900, "pro": 300}
#: tickers each plan accepts in one call to `symbols`
ASSETS_PER_REQUEST = {"free": 1, "startup": 10, "pro": 20}
#: history depth each plan may request (free: 3 months)
HISTORY_RANGES = {
    "free": ("1mo", "3mo"),
    "startup": ("1mo", "3mo", "1y"),
    "pro": ("1mo", "3mo", "1y", "5y"),
}
#: brapi subType -> Voryn asset_type. Other fund kinds (FIP, FIDC, FI-Infra, FI-Agro) are
#: not supported yet and are skipped.
ASSET_TYPES = {"stock": "STOCK", "unit": "STOCK", "fii": "FII", "etf": "ETF", "bdr": "BDR"}

_RETRYABLE = {500, 502, 503, 504}
_PLAN_LIMIT_CODES = {"INVALID_RANGE", "INVALID_INTERVAL", "QUOTES_PER_REQUEST_EXCEEDED"}
# brapi's own documented fallback when a 429 has no Retry-After.
_DEFAULT_RETRY_AFTER_SECONDS = 60
_MAX_ATTEMPTS = 3
_MAX_BACKOFF_SECONDS = 30.0
_PAGE_SIZE = 1000
_MAX_PAGES = 10
_SYMBOL = re.compile(r"^[A-Z0-9]{4,12}$")
# Fractional-lot tickers (PETR4F): same company as the round lot, with tiny volumes and
# erratic changes (+260% on 3 shares). Listing them would duplicate assets and distort movers.
_FRACTIONAL = re.compile(r"^[A-Z0-9]{4}\d{1,2}F$")


class ProviderAccessError(ProviderError):
    """401: the token is missing or invalid."""


class ProviderPlanError(ProviderError):
    """403, or a 400 over a plan limit: this plan does not include the request."""


class ProviderNotFoundError(ProviderError):
    """404: brapi has no data for the request."""


class ProviderRateLimitError(ProviderError):
    """429: monthly quota or concurrency used up; nothing may be sent for `retry_after` s."""

    def __init__(self, retry_after: int, path: str, code: str | None) -> None:
        super().__init__(f"brapi {path} responded 429 ({code}), retry after {retry_after}s")
        self.retry_after = retry_after


@dataclass(frozen=True, slots=True)
class ExchangeQuote:
    symbol: str
    name: str
    asset_type: str
    sector: str | None
    logo_url: str | None
    currency: str
    price: Decimal
    change_pct: Decimal | None
    volume: Decimal | None
    market_cap: Decimal | None


@dataclass(frozen=True, slots=True)
class SessionDetail:
    """Figures of the current session and year; any of them may be missing upstream."""

    open: Decimal | None
    day_high: Decimal | None
    day_low: Decimal | None
    previous_close: Decimal | None
    week52_low: Decimal | None
    week52_high: Decimal | None


@dataclass(frozen=True, slots=True)
class DailyBar:
    day: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    adjusted_close: Decimal | None
    volume: Decimal | None


@dataclass(frozen=True, slots=True)
class FiiFundamentals:
    nav_per_share: Decimal | None
    #: fraction (0.09 = 9%), computed by brapi on the price of the reference month
    dividend_yield_12m: Decimal | None
    #: month the NAV refers to; published with a lag
    as_of: date | None
    segment: str | None


@dataclass(frozen=True, slots=True)
class FiiPayment:
    payment_date: date
    rate: Decimal


class _Quote(BaseModel):
    model_config = ConfigDict(extra="ignore")

    lastPrice: Decimal = Field(gt=0)  # noqa: N815 - upstream field name
    changePercent: Decimal | None = Field(default=None, gt=-100, lt=10000)  # noqa: N815
    volume: Decimal | None = Field(default=None, ge=0)
    marketCap: Decimal | None = Field(default=None, ge=0)  # noqa: N815


class _Ticker(BaseModel):
    model_config = ConfigDict(extra="ignore")

    symbol: str
    name: str | None = None
    longName: str | None = None  # noqa: N815
    subType: str | None = None  # noqa: N815
    currency: str = "BRL"
    sector: str | None = Field(default=None, max_length=128)
    isActive: bool = True  # noqa: N815
    logoUrl: str | None = Field(default=None, max_length=512)  # noqa: N815
    quote: _Quote


class _Detail(BaseModel):
    model_config = ConfigDict(extra="ignore")

    regularMarketOpen: Decimal | None = Field(default=None, gt=0)  # noqa: N815
    regularMarketDayHigh: Decimal | None = Field(default=None, gt=0)  # noqa: N815
    regularMarketDayLow: Decimal | None = Field(default=None, gt=0)  # noqa: N815
    regularMarketPreviousClose: Decimal | None = Field(default=None, gt=0)  # noqa: N815
    fiftyTwoWeekLow: Decimal | None = Field(default=None, gt=0)  # noqa: N815
    fiftyTwoWeekHigh: Decimal | None = Field(default=None, gt=0)  # noqa: N815


class _FiiIndicators(BaseModel):
    model_config = ConfigDict(extra="ignore")

    navPerShare: Decimal | None = Field(default=None, gt=0)  # noqa: N815
    dividendYield12m: Decimal | None = Field(default=None, ge=0)  # noqa: N815
    asOfDate: str | None = None  # noqa: N815
    segmentType: str | None = Field(default=None, max_length=32)  # noqa: N815


class _FiiDividend(BaseModel):
    model_config = ConfigDict(extra="ignore")

    paymentDate: str | None = None  # noqa: N815
    rate: Decimal | None = None
    label: str | None = None


class _Bar(BaseModel):
    model_config = ConfigDict(extra="ignore")

    date: int
    open: Decimal = Field(gt=0)
    high: Decimal = Field(gt=0)
    low: Decimal = Field(gt=0)
    close: Decimal = Field(gt=0)
    volume: Decimal | None = Field(default=None, ge=0)
    adjustedClose: Decimal | None = Field(default=None, gt=0)  # noqa: N815


def repair_text(value: str) -> str:
    """Undo UTF-8 text that was decoded as Windows-1252 upstream ("BALCÃƒO" -> "BALCÃO")."""
    if "Ã" not in value and "Â" not in value:
        return value
    try:
        return value.encode("cp1252").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return value


def _display_name(row: _Ticker) -> str:
    name = repair_text((row.name or "").strip())
    if not name or name.upper() == row.symbol:
        name = repair_text((row.longName or "").strip())
    return (name or row.symbol)[:128]


class BrapiProvider:
    name = SOURCE

    def __init__(
        self, client: httpx.AsyncClient | None = None, *, max_attempts: int = _MAX_ATTEMPTS
    ) -> None:
        settings = get_settings()
        headers = {"Accept": "application/json", "User-Agent": "Voryn/0.1"}
        if settings.brapi_token:
            headers["Authorization"] = f"Bearer {settings.brapi_token.get_secret_value()}"
        self._client = client or httpx.AsyncClient(
            base_url=settings.brapi_base_url,
            headers=headers,
            timeout=httpx.Timeout(20.0, connect=5.0),
        )
        self._owns_client = client is None
        self._max_attempts = max_attempts
        self.delay_seconds = DELAY_SECONDS[settings.brapi_plan]
        self._assets_per_request = ASSETS_PER_REQUEST[settings.brapi_plan]
        #: upstream requests made by this instance (the free plan is metered monthly)
        self.requests = 0

    @staticmethod
    def delay_for(plan: str) -> int:
        return DELAY_SECONDS[plan]

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _get(self, path: str, params: dict[str, Any]) -> Any:
        """GET following brapi's error contract: 400/401/403/404 are final, 429 waits for
        Retry-After, 5xx and network errors back off. Logs carry the route and brapi's error
        code, never the token."""
        last_error: Exception | None = None
        for attempt in range(1, self._max_attempts + 1):
            self.requests += 1
            try:
                response = await self._client.get(path, params=params)
            except httpx.TransportError as exc:
                last_error = exc
                delay = min(2.0**attempt, _MAX_BACKOFF_SECONDS)
            else:
                status = response.status_code
                if status == 200:
                    try:
                        return json.loads(response.text, parse_float=Decimal)
                    except json.JSONDecodeError as exc:
                        raise ProviderError(f"brapi returned invalid JSON for {path}") from exc
                code = _error_code(response)
                if status == 429:
                    wait = _retry_after(response)
                    last_error = ProviderRateLimitError(wait, path, code)
                    # Monthly quota: the wait can be days, so it is the caller's to honour.
                    if wait > _MAX_BACKOFF_SECONDS or attempt == self._max_attempts:
                        raise last_error
                    delay = float(wait)
                elif status in _RETRYABLE:
                    last_error = ProviderError(f"brapi {path} responded {status} ({code})")
                    delay = min(2.0**attempt, _MAX_BACKOFF_SECONDS)
                elif status == 401:
                    raise ProviderAccessError(f"brapi {path} responded 401 ({code})")
                elif status == 403 or code in _PLAN_LIMIT_CODES:
                    raise ProviderPlanError(f"brapi {path} responded {status} ({code})")
                elif status == 404:
                    raise ProviderNotFoundError(f"brapi {path} responded 404 ({code})")
                else:
                    raise ProviderError(f"brapi {path} responded {status} ({code})")
            if attempt < self._max_attempts:
                logger.warning("brapi_retry", path=path, attempt=attempt, delay=delay)
                await asyncio.sleep(delay)
        if isinstance(last_error, ProviderRateLimitError):
            raise last_error
        raise ProviderError(f"brapi {path} failed after retries") from last_error

    async def fetch_catalogue(self) -> list[ExchangeQuote]:
        """Every active, supported B3 instrument with its latest (delayed) quote."""
        quotes: dict[str, ExchangeQuote] = {}
        dropped = 0
        for page in range(1, _MAX_PAGES + 1):
            payload = await self._get("/v2/tickers", {"page": page, "limit": _PAGE_SIZE})
            try:
                rows = payload["results"]
                has_next = bool(payload["pagination"]["hasNextPage"])
            except (KeyError, TypeError) as exc:
                raise ProviderError("brapi /v2/tickers returned an unexpected payload") from exc
            for raw in rows:
                parsed = _to_quote(raw)
                if parsed is None:
                    dropped += 1
                    continue
                quotes.setdefault(parsed.symbol, parsed)
            if not has_next:
                break
        else:
            logger.warning("brapi_catalogue_truncated", pages=_MAX_PAGES)
        if not quotes:
            raise ProviderError("brapi returned an empty catalogue")
        if dropped:
            logger.info("brapi_rows_skipped", count=dropped)
        return list(quotes.values())

    async def fetch_session_details(self, symbols: Sequence[str]) -> dict[str, SessionDetail]:
        """Day range, open, previous close and 52-week range by requested ticker, as few calls
        as the plan allows (free: 1 asset per call). A ticker brapi does not know is left out.
        `regularMarketTime` is ignored: it is when brapi refreshed its data, not a trade time.
        """
        for symbol in symbols:
            _check_symbol(symbol)
        details: dict[str, SessionDetail] = {}
        size = self._assets_per_request
        for start in range(0, len(symbols), size):
            chunk = symbols[start : start + size]
            try:
                payload = await self._get("/v2/stocks/quote", {"symbols": ",".join(chunk)})
            except ProviderNotFoundError:
                continue  # "if no ticker has a quote, the response is 404"
            try:
                rows = payload["results"]
                for row in rows:
                    data = _Detail.model_validate(row["data"])
                    details[row.get("requestedSymbol") or row["symbol"]] = SessionDetail(
                        open=data.regularMarketOpen,
                        day_high=data.regularMarketDayHigh,
                        day_low=data.regularMarketDayLow,
                        previous_close=data.regularMarketPreviousClose,
                        week52_low=data.fiftyTwoWeekLow,
                        week52_high=data.fiftyTwoWeekHigh,
                    )
            except (KeyError, TypeError, ValidationError) as exc:
                raise ProviderError("brapi quote returned an unexpected payload") from exc
        return details

    async def fetch_session_detail(self, symbol: str) -> SessionDetail:
        details = await self.fetch_session_details([symbol])
        if symbol not in details:
            raise ProviderNotFoundError(f"brapi has no quote for {symbol}")
        return details[symbol]

    async def fetch_fii_fundamentals(self, symbol: str) -> FiiFundamentals:
        _check_symbol(symbol)
        payload = await self._get("/v2/fii/indicators", {"symbols": symbol})
        try:
            rows = payload["fiis"]
            if not rows:
                raise ProviderNotFoundError(f"brapi has no indicators for {symbol}")
            row = _FiiIndicators.model_validate(rows[0])
        except (KeyError, TypeError, ValidationError) as exc:
            raise ProviderError("brapi fii/indicators returned an unexpected payload") from exc
        return FiiFundamentals(
            nav_per_share=row.navPerShare,
            dividend_yield_12m=row.dividendYield12m,
            as_of=_parse_day(row.asOfDate),
            segment=row.segmentType,
        )

    async def fetch_fii_payments(self, symbol: str) -> list[FiiPayment]:
        """Income paid per share. Rows without a date or a positive rate are dropped, and so is
        anything but income: an amortization returns capital and would inflate the yield."""
        _check_symbol(symbol)
        payload = await self._get("/v2/fii/dividends", {"symbols": symbol})
        try:
            rows = payload["dividends"]
        except (KeyError, TypeError) as exc:
            raise ProviderError("brapi fii/dividends returned an unexpected payload") from exc
        payments: list[FiiPayment] = []
        for raw in rows:
            try:
                row = _FiiDividend.model_validate(raw)
            except ValidationError:
                continue
            day = _parse_day(row.paymentDate)
            label = (row.label or "").upper()
            if day and row.rate is not None and row.rate > 0 and "RENDIMENTO" in label:
                payments.append(FiiPayment(day, row.rate))
        return payments

    async def fetch_daily_history(self, symbol: str, range_: str = "3mo") -> list[DailyBar]:
        """Daily bars, oldest first. History depth depends on the plan (free: 3 months)."""
        _check_symbol(symbol)
        payload = await self._get(
            "/v2/stocks/historical", {"symbols": symbol, "range": range_, "interval": "1d"}
        )
        try:
            results = payload["results"]
            rows = results[0]["data"]["historicalDataPrice"] if results else []
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("brapi historical returned an unexpected payload") from exc
        bars: dict[date, DailyBar] = {}
        for raw in rows:
            try:
                bar = _Bar.model_validate(raw)
            except ValidationError:
                continue
            if not bar.low <= min(bar.open, bar.close) <= max(bar.open, bar.close) <= bar.high:
                continue
            day = datetime.fromtimestamp(bar.date, UTC).date()
            bars[day] = DailyBar(
                day, bar.open, bar.high, bar.low, bar.close, bar.adjustedClose, bar.volume
            )
        return [bars[d] for d in sorted(bars)]


def _parse_day(value: str | None) -> date | None:
    """First 10 chars of "2026-09-01 00:00:00+00" or "2026-11-16T03:00:00.000Z"."""
    try:
        return date.fromisoformat(value[:10]) if value else None
    except ValueError:
        return None


def _check_symbol(symbol: str) -> None:
    if not _SYMBOL.match(symbol):
        raise ValueError(f"invalid B3 symbol: {symbol!r}")


def _to_quote(raw: Any) -> ExchangeQuote | None:
    try:
        row = _Ticker.model_validate(raw)
    except ValidationError:
        return None
    symbol = row.symbol.strip().upper()
    asset_type = ASSET_TYPES.get(row.subType or "")
    if not row.isActive or asset_type is None or not _SYMBOL.match(symbol):
        return None
    if _FRACTIONAL.match(symbol):
        return None
    if row.currency != "BRL":
        return None
    logo = row.logoUrl if row.logoUrl and row.logoUrl.startswith("https://") else None
    return ExchangeQuote(
        symbol=symbol,
        name=_display_name(row.model_copy(update={"symbol": symbol})),
        asset_type=asset_type,
        sector=row.sector,
        logo_url=logo,
        currency="BRL",
        price=row.quote.lastPrice,
        change_pct=row.quote.changePercent,
        volume=row.quote.volume,
        market_cap=row.quote.marketCap,
    )


def _retry_after(response: httpx.Response) -> int:
    value = response.headers.get("retry-after", "")
    return int(value) if value.isdigit() else _DEFAULT_RETRY_AFTER_SECONDS


def _error_code(response: httpx.Response) -> str | None:
    try:
        body = response.json()
    except ValueError:
        return None
    code = body.get("code") if isinstance(body, dict) else None
    return str(code) if code else None
