"""Binance public market data (candles) via data-api.binance.vision.

The `data-api.binance.vision` host serves only public market data and, unlike
api.binance.com, is not geo-restricted. No API key is used or needed.

Prices are quoted in USDT, treated as a USD proxy (documented to users).
"""

import asyncio
import json
from datetime import UTC, datetime
from decimal import Decimal

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger
from app.modules.market_data.providers.base import Candle, ProviderError, Timeframe

logger = get_logger(__name__)

SOURCE = "binance"
QUOTE = "USDT"
_RETRYABLE = {418, 429, 500, 502, 503, 504}
# Symbols that are themselves USD-pegged have no meaningful */USDT chart.
_NO_PAIR = frozenset({"USDT"})


class BinanceCandleProvider:
    name = SOURCE

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(
            base_url=get_settings().binance_base_url,
            timeout=httpx.Timeout(15.0, connect=5.0),
            headers={"User-Agent": "Voryn/0.1"},
        )
        self._owns_client = client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def pair_for(self, symbol: str) -> str | None:
        symbol = symbol.upper()
        if symbol in _NO_PAIR or not symbol.isalnum():
            return None
        return f"{symbol}{QUOTE}"

    async def fetch_candles(self, pair: str, timeframe: Timeframe, limit: int) -> list[Candle]:
        params: dict[str, str | int] = {
            "symbol": pair,
            "interval": timeframe,
            "limit": min(limit, 1000),
        }
        response: httpx.Response | None = None
        for attempt in range(1, 4):
            try:
                response = await self._client.get("/api/v3/klines", params=params)
            except httpx.TransportError as exc:
                if attempt == 3:
                    raise ProviderError("Binance unreachable") from exc
                await asyncio.sleep(2**attempt)
                continue
            if response.status_code not in _RETRYABLE:
                break
            retry_after = response.headers.get("retry-after", "")
            await asyncio.sleep(
                min(float(retry_after) if retry_after.isdigit() else 2**attempt, 30)
            )
        assert response is not None
        if response.status_code == 400:
            # {"code": -1121, "msg": "Invalid symbol."}: the asset is not listed against USDT.
            raise UnknownPairError(pair)
        if response.status_code != 200:
            raise ProviderError(f"Binance klines responded {response.status_code}")
        try:
            rows = json.loads(response.text)
        except json.JSONDecodeError as exc:
            raise ProviderError("Binance returned invalid JSON") from exc
        return parse_klines(rows)


class UnknownPairError(ProviderError):
    def __init__(self, pair: str) -> None:
        self.pair = pair
        super().__init__(f"Binance has no market {pair}")


def parse_klines(rows: object, now: datetime | None = None) -> list[Candle]:
    """Validate raw klines; malformed or inconsistent rows are dropped, never stored."""
    if not isinstance(rows, list):
        raise ProviderError("Binance klines payload is not a list")
    now_ms = int((now or datetime.now(UTC)).timestamp() * 1000)
    candles: list[Candle] = []
    rejected = 0
    last_open = -1
    for row in rows:
        try:
            open_ms, o, h, low, c, vol, close_ms, quote_vol = (
                int(row[0]), Decimal(row[1]), Decimal(row[2]), Decimal(row[3]),
                Decimal(row[4]), Decimal(row[5]), int(row[6]), Decimal(row[7]),
            )  # fmt: skip
        except (TypeError, ValueError, IndexError, ArithmeticError):
            rejected += 1
            continue
        consistent = (
            open_ms > last_open
            and min(o, h, low, c) > 0
            and h >= max(o, c)
            and low <= min(o, c)
            and vol >= 0
            and quote_vol >= 0
        )
        if not consistent:
            rejected += 1
            continue
        last_open = open_ms
        candles.append(
            Candle(
                open_time=datetime.fromtimestamp(open_ms / 1000, UTC),
                open=o,
                high=h,
                low=low,
                close=c,
                volume=vol,
                quote_volume=quote_vol,
                closed=close_ms < now_ms,
            )
        )
    if rejected:
        logger.warning("binance_klines_rejected", rejected=rejected, accepted=len(candles))
    return candles
