"""CoinGecko adapter (https://docs.coingecko.com).

- JSON numbers are parsed as Decimal to avoid float rounding of prices.
- Every row is validated; malformed rows are dropped and logged instead of persisted.
- 429/5xx/timeouts are retried with exponential backoff, honouring Retry-After.
- Attribution "Data provided by CoinGecko" is required by their terms and shown in the UI.
"""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.core.config import get_settings
from app.core.logging import get_logger
from app.modules.market_data.providers.base import FxQuote, MarketQuote, ProviderError

logger = get_logger(__name__)

SOURCE = "coingecko"
_RETRYABLE = {429, 500, 502, 503, 504}
_MAX_ATTEMPTS = 3
_MAX_BACKOFF_SECONDS = 30.0
# A quote stamped this far in the future means a broken upstream clock or payload.
_MAX_CLOCK_SKEW = timedelta(minutes=5)


class _MarketRow(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1, max_length=128)
    symbol: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=128)
    image: str | None = None
    market_cap_rank: int | None = None
    current_price: Decimal = Field(ge=0)
    market_cap: Decimal | None = Field(default=None, ge=0)
    fully_diluted_valuation: Decimal | None = Field(default=None, ge=0)
    total_volume: Decimal | None = Field(default=None, ge=0)
    high_24h: Decimal | None = Field(default=None, ge=0)
    low_24h: Decimal | None = Field(default=None, ge=0)
    price_change_percentage_1h_in_currency: Decimal | None = None
    price_change_percentage_24h_in_currency: Decimal | None = None
    price_change_percentage_7d_in_currency: Decimal | None = None
    circulating_supply: Decimal | None = Field(default=None, ge=0)
    total_supply: Decimal | None = Field(default=None, ge=0)
    max_supply: Decimal | None = Field(default=None, ge=0)
    ath: Decimal | None = Field(default=None, ge=0)
    ath_change_percentage: Decimal | None = None
    ath_date: datetime | None = None
    last_updated: datetime

    @field_validator("last_updated")
    @classmethod
    def _not_in_future(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        if value > datetime.now(UTC) + _MAX_CLOCK_SKEW:
            raise ValueError("last_updated is in the future")
        return value

    @field_validator("image")
    @classmethod
    def _https_only(cls, value: str | None) -> str | None:
        if value and not value.startswith("https://"):
            return None
        return value[:512] if value else None


class CoinGeckoProvider:
    name = SOURCE

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        settings = get_settings()
        headers = {"Accept": "application/json", "User-Agent": "Voryn/0.1"}
        if settings.coingecko_api_key:
            header = (
                "x-cg-pro-api-key" if settings.coingecko_api_plan == "pro" else "x-cg-demo-api-key"
            )
            headers[header] = settings.coingecko_api_key.get_secret_value()
        self._client = client or httpx.AsyncClient(
            base_url=settings.coingecko_base_url,
            headers=headers,
            timeout=httpx.Timeout(15.0, connect=5.0),
        )
        self._owns_client = client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        last_error: Exception | None = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
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
                        raise ProviderError(f"CoinGecko returned invalid JSON for {path}") from exc
                if response.status_code not in _RETRYABLE:
                    raise ProviderError(f"CoinGecko {path} responded {response.status_code}")
                last_error = ProviderError(f"CoinGecko {path} responded {response.status_code}")
                delay = _retry_after(response) or min(2.0**attempt, _MAX_BACKOFF_SECONDS)
            if attempt < _MAX_ATTEMPTS:
                logger.warning("coingecko_retry", path=path, attempt=attempt, delay=delay)
                await asyncio.sleep(delay)
        raise ProviderError(
            f"CoinGecko {path} failed after {_MAX_ATTEMPTS} attempts"
        ) from last_error

    async def fetch_top_markets(self, vs_currency: str, limit: int) -> list[MarketQuote]:
        payload = await self._get(
            "/coins/markets",
            {
                "vs_currency": vs_currency.lower(),
                "order": "market_cap_desc",
                "per_page": min(limit, 250),
                "page": 1,
                "sparkline": "false",
                "price_change_percentage": "1h,24h,7d",
                "precision": "full",
            },
        )
        if not isinstance(payload, list):
            raise ProviderError("CoinGecko /coins/markets returned an unexpected payload")
        quotes: list[MarketQuote] = []
        rejected = 0
        for raw in payload:
            try:
                row = _MarketRow.model_validate(raw)
            except ValidationError:
                rejected += 1
                continue
            quotes.append(_to_quote(row, vs_currency.upper()))
        if rejected:
            logger.warning("coingecko_rows_rejected", rejected=rejected, accepted=len(quotes))
        if not quotes:
            raise ProviderError("CoinGecko returned no valid market rows")
        return quotes

    async def fetch_fx_rate(self, base: str, quote: str) -> FxQuote:
        # /exchange_rates is BTC-denominated: base→quote = rate(quote) / rate(base).
        payload = await self._get("/exchange_rates")
        try:
            rates = payload["rates"]
            base_value = Decimal(rates[base.lower()]["value"])
            quote_value = Decimal(rates[quote.lower()]["value"])
        except (KeyError, TypeError, ArithmeticError) as exc:
            raise ProviderError("CoinGecko /exchange_rates payload is missing currencies") from exc
        if base_value <= 0 or quote_value <= 0:
            raise ProviderError("CoinGecko /exchange_rates returned non-positive rates")
        return FxQuote(
            base_currency=base.upper(),
            quote_currency=quote.upper(),
            rate=quote_value / base_value,
            observed_at=datetime.now(UTC),
        )


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("retry-after")
    if value and value.isdigit():
        return min(float(value), _MAX_BACKOFF_SECONDS)
    return None


def _to_quote(row: _MarketRow, quote_currency: str) -> MarketQuote:
    return MarketQuote(
        source_id=row.id,
        symbol=row.symbol.upper(),
        name=row.name,
        image_url=row.image,
        market_cap_rank=row.market_cap_rank,
        quote_currency=quote_currency,
        price=row.current_price,
        market_cap=row.market_cap,
        fully_diluted_valuation=row.fully_diluted_valuation,
        total_volume=row.total_volume,
        high_24h=row.high_24h,
        low_24h=row.low_24h,
        change_pct_1h=row.price_change_percentage_1h_in_currency,
        change_pct_24h=row.price_change_percentage_24h_in_currency,
        change_pct_7d=row.price_change_percentage_7d_in_currency,
        circulating_supply=row.circulating_supply,
        total_supply=row.total_supply,
        max_supply=row.max_supply,
        ath=row.ath,
        ath_change_pct=row.ath_change_percentage,
        ath_date=row.ath_date,
        source_updated_at=row.last_updated,
    )
