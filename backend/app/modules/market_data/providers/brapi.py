"""brapi.dev adapter for B3 (https://brapi.dev/docs).

- The catalogue endpoint (`/v2/tickers`) returns every listed instrument with its latest
  quote, ~1000 per page, so one sync costs a handful of requests (free plan: 15k/month).
- Quotes are delayed by plan (free 30 min, startup 15 min, pro 5 min); the delay is
  declared with every quote so nothing downstream presents it as real time.
- brapi is not a licensed B3 market data distributor: production display of B3 quotes
  stays behind `MARKETS_ENABLED` until licensing is settled (docs/MULTIMARKET_PLAN.md).
- JSON numbers are parsed as Decimal; malformed rows are dropped, never stored.
- 429/5xx/timeouts are retried with exponential backoff, honouring Retry-After.
"""

import asyncio
import json
import re
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
#: brapi subType -> Voryn asset_type. Other fund kinds (FIP, FIDC, FI-Infra, FI-Agro) are
#: not supported yet and are skipped.
ASSET_TYPES = {"stock": "STOCK", "unit": "STOCK", "fii": "FII", "etf": "ETF", "bdr": "BDR"}

_RETRYABLE = {429, 500, 502, 503, 504}
_MAX_ATTEMPTS = 3
_MAX_BACKOFF_SECONDS = 30.0
_PAGE_SIZE = 1000
_MAX_PAGES = 10
_SYMBOL = re.compile(r"^[A-Z0-9]{4,12}$")


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
class DailyBar:
    day: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    adjusted_close: Decimal | None
    volume: Decimal


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


class _Bar(BaseModel):
    model_config = ConfigDict(extra="ignore")

    date: int
    open: Decimal = Field(gt=0)
    high: Decimal = Field(gt=0)
    low: Decimal = Field(gt=0)
    close: Decimal = Field(gt=0)
    volume: Decimal = Field(ge=0)
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

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
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
        self.delay_seconds = DELAY_SECONDS[settings.brapi_plan]
        #: upstream requests made by this instance (the free plan is metered monthly)
        self.requests = 0

    @staticmethod
    def delay_for(plan: str) -> int:
        return DELAY_SECONDS[plan]

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _get(self, path: str, params: dict[str, Any]) -> Any:
        last_error: Exception | None = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            self.requests += 1
            try:
                response = await self._client.get(path, params=params)
            except httpx.TransportError as exc:
                last_error = exc
                delay = min(2.0**attempt, _MAX_BACKOFF_SECONDS)
            else:
                if response.status_code == 200:
                    try:
                        return json.loads(response.text, parse_float=Decimal)
                    except json.JSONDecodeError as exc:
                        raise ProviderError(f"brapi returned invalid JSON for {path}") from exc
                if response.status_code not in _RETRYABLE:
                    raise ProviderError(f"brapi {path} responded {response.status_code}")
                last_error = ProviderError(f"brapi {path} responded {response.status_code}")
                delay = _retry_after(response) or min(2.0**attempt, _MAX_BACKOFF_SECONDS)
            if attempt < _MAX_ATTEMPTS:
                logger.warning("brapi_retry", path=path, attempt=attempt, delay=delay)
                await asyncio.sleep(delay)
        raise ProviderError(f"brapi {path} failed after {_MAX_ATTEMPTS} attempts") from last_error

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

    async def fetch_daily_history(self, symbol: str, range_: str = "3mo") -> list[DailyBar]:
        """Daily bars, oldest first. History depth depends on the plan (free: 3 months)."""
        if not _SYMBOL.match(symbol):
            raise ValueError(f"invalid B3 symbol: {symbol!r}")
        payload = await self._get(
            "/v2/stocks/historical", {"symbols": symbol, "range": range_, "interval": "1d"}
        )
        try:
            rows = payload["results"][0]["data"]["historicalDataPrice"]
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


def _to_quote(raw: Any) -> ExchangeQuote | None:
    try:
        row = _Ticker.model_validate(raw)
    except ValidationError:
        return None
    symbol = row.symbol.strip().upper()
    asset_type = ASSET_TYPES.get(row.subType or "")
    if not row.isActive or asset_type is None or not _SYMBOL.match(symbol):
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


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("retry-after")
    if value and value.isdigit():
        return min(float(value), _MAX_BACKOFF_SECONDS)
    return None
