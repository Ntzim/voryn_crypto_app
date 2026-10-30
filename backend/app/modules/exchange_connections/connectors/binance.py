"""Binance spot account, read-only (signed REST endpoints).

Scope (docs/EXCHANGES.md): spot trades against BRL and dollar stablecoins, crypto deposits
and withdrawals. Convert, Earn, P2P, Pay and futures are not read; reconciliation shows
the difference they leave in the balances.
"""

import asyncio
import functools
import hashlib
import hmac
import time
from collections.abc import Callable, Coroutine, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode

import httpx

from app.core.config import get_settings
from app.modules.exchange_connections.connectors.base import (
    ConnectorAuthError,
    ConnectorError,
    ExternalRecord,
    Permissions,
    SyncBatch,
)

QUOTES = ("BRL", "USDT", "USDC", "FDUSD")
#: flags that grant no write capability; ipRestrict only narrows where the key works
READ_FLAGS = {"enableReading", "enableFixReadOnly", "ipRestrict"}
INITIAL_LOOKBACK = timedelta(days=365)
#: Binance accepts at most 90 days per deposit/withdrawal query
WINDOW = timedelta(days=89)
#: completed deposits/withdrawals can appear late; re-scan this much on every sync
OVERLAP = timedelta(days=3)
PAGE = 1000
DEPOSIT_SUCCESS = 1
WITHDRAWAL_COMPLETED = 6
#: transient failures are retried this many times, waiting BACKOFF_SECONDS × 2^n
RETRIES = 2
BACKOFF_SECONDS = 1.0
_AUTH_CODES = {-2014, -2015, -1022, -2008}


def _validated[**P, R](
    method: Callable[P, Coroutine[Any, Any, R]],
) -> Callable[P, Coroutine[Any, Any, R]]:
    """A payload of an unexpected shape (missing field, wrong type, non-numeric amount,
    body that is not JSON) becomes a ConnectorError with a generic message: the sync of
    this connection fails cleanly, without the raw response, and no partial data is kept."""

    @functools.wraps(method)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return await method(*args, **kwargs)
        except (KeyError, IndexError, TypeError, ValueError, ArithmeticError, AttributeError):
            raise ConnectorError("A Binance respondeu em um formato inesperado.") from None

    return wrapper


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _from_ms(ms: int | str) -> datetime:
    return datetime.fromtimestamp(int(ms) / 1000, UTC)


class BinanceConnector:
    exchange_id = "binance"

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        *,
        base_url: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        now: Any = None,
        backoff_seconds: float = BACKOFF_SECONDS,
    ) -> None:
        self._key, self._secret = api_key, api_secret.encode()
        self._client = httpx.AsyncClient(
            base_url=base_url or get_settings().binance_private_base_url,
            timeout=20,
            transport=transport,
            headers={"User-Agent": "Voryn/1.0"},
        )
        self._offset_ms = 0
        self._now = now or (lambda: datetime.now(UTC))
        self._backoff = backoff_seconds

    async def aclose(self) -> None:
        await self._client.aclose()

    # ------------------------------------------------------------------ transport

    async def _send(
        self, url: str, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None
    ) -> httpx.Response:
        """GET with retries for transient failures (network errors, 5xx), backing off
        exponentially. 418/429 are not retried: Binance bans clients that keep calling."""
        for attempt in range(RETRIES + 1):
            last = attempt == RETRIES
            try:
                response = await self._client.get(url, params=params, headers=headers)
            except httpx.HTTPError as exc:
                if last:
                    raise ConnectorError("Não foi possível conectar à Binance.") from exc
            else:
                if response.status_code < 500 or last:
                    return response
            await asyncio.sleep(self._backoff * 2**attempt)
        raise AssertionError("unreachable")

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return self._parse(await self._send(path, params))

    async def _signed(self, path: str, params: dict[str, Any] | None = None) -> Any:
        for attempt in range(2):
            query = urlencode(
                {
                    **(params or {}),
                    "timestamp": int(time.time() * 1000) + self._offset_ms,
                    "recvWindow": 10000,
                }
            )
            signature = hmac.new(self._secret, query.encode(), hashlib.sha256).hexdigest()
            # Retries reuse the signature: they finish well inside recvWindow (10 s).
            response = await self._send(
                f"{path}?{query}&signature={signature}", headers={"X-MBX-APIKEY": self._key}
            )
            if attempt == 0 and _code(response) == -1021:  # clock drift: resync and retry once
                server = await self._get("/api/v3/time")
                self._offset_ms = int(server["serverTime"]) - int(time.time() * 1000)
                continue
            return self._parse(response)
        raise ConnectorError("Relógio fora de sincronia com a Binance.")

    @staticmethod
    def _parse(response: httpx.Response) -> Any:
        if response.status_code in (418, 429):
            raise ConnectorError("Limite de requisições da Binance atingido. Tente mais tarde.")
        code = _code(response)
        if response.status_code == 401 or code in _AUTH_CODES:
            raise ConnectorAuthError("A Binance recusou a chave de API (inválida ou revogada).")
        if response.status_code >= 400:
            message = _message(response) or f"HTTP {response.status_code}"
            raise ConnectorError(f"Erro da Binance: {message}")
        return response.json()

    # ------------------------------------------------------------------ contract

    @_validated
    async def permissions(self) -> Permissions:
        data = await self._signed("/sapi/v1/account/apiRestrictions")
        flags = {k: v for k, v in data.items() if isinstance(v, bool)}
        # Unknown flags count as write permissions: new capabilities are rejected by default.
        writes = sorted(k for k, v in flags.items() if v and k not in READ_FLAGS)
        return Permissions(can_read=bool(flags.get("enableReading")), write_permissions=writes)

    @_validated
    async def balances(self) -> dict[str, Decimal]:
        data = await self._signed("/api/v3/account", {"omitZeroBalances": "true"})
        out: dict[str, Decimal] = {}
        for b in data.get("balances", []):
            total = Decimal(b["free"]) + Decimal(b["locked"])
            if total > 0:
                out[b["asset"].upper()] = total
        return out

    @_validated
    async def history(self, cursor: dict[str, Any], assets: Sequence[str]) -> SyncBatch:
        batch = SyncBatch(cursor={**cursor})
        # Transfers first: a coin deposited and later sold out still gets its markets read.
        await self._transfers(batch)
        moved = {str(r.data["coin"]) for r in batch.records}
        await self._trades(batch, {a.upper() for a in assets} | moved)
        return batch

    async def _trades(self, batch: SyncBatch, assets: set[str]) -> None:
        info = await self._get("/api/v3/exchangeInfo", {"permissions": "SPOT"})
        markets = [
            (s["symbol"], s["baseAsset"].upper(), s["quoteAsset"].upper())
            for s in info.get("symbols", [])
            if s["quoteAsset"].upper() in QUOTES and s["baseAsset"].upper() in assets
        ]
        positions: dict[str, int] = dict(batch.cursor.get("trades", {}))
        for symbol, base, quote in sorted(markets):
            from_id = positions.get(symbol, 0)
            while True:
                rows = await self._signed(
                    "/api/v3/myTrades", {"symbol": symbol, "fromId": from_id, "limit": PAGE}
                )
                for t in rows:
                    batch.records.append(
                        ExternalRecord(
                            kind="trade",
                            external_id=f"trade:{symbol}:{t['id']}",
                            occurred_at=_from_ms(t["time"]),
                            data={
                                "symbol": symbol,
                                "base": base,
                                "quote": quote,
                                "side": "buy" if t["isBuyer"] else "sell",
                                "price": t["price"],
                                "qty": t["qty"],
                                "quote_qty": t["quoteQty"],
                                "commission": t["commission"],
                                "commission_asset": str(t["commissionAsset"]).upper(),
                                "order_id": t["orderId"],
                            },
                        )
                    )
                if rows:
                    from_id = int(rows[-1]["id"]) + 1
                    positions[symbol] = from_id
                if len(rows) < PAGE:
                    break
        batch.cursor["trades"] = positions

    async def _transfers(self, batch: SyncBatch) -> None:
        now = self._now()
        since = (
            datetime.fromisoformat(batch.cursor["transfers_since"])
            if "transfers_since" in batch.cursor
            else now - INITIAL_LOOKBACK
        )
        start = since
        while start < now:
            end = min(start + WINDOW, now)
            window = {"startTime": _ms(start), "endTime": _ms(end)}
            for d in await self._signed("/sapi/v1/capital/deposit/hisrec", window):
                if int(d.get("status", -1)) != DEPOSIT_SUCCESS:
                    continue
                batch.records.append(
                    ExternalRecord(
                        kind="deposit",
                        external_id=f"deposit:{d.get('id') or d.get('txId')}",
                        occurred_at=_from_ms(d["insertTime"]),
                        data={
                            "coin": str(d["coin"]).upper(),
                            "amount": d["amount"],
                            "network": d.get("network"),
                            "tx_id": d.get("txId"),
                        },
                    )
                )
            for w in await self._signed("/sapi/v1/capital/withdraw/history", window):
                if int(w.get("status", -1)) != WITHDRAWAL_COMPLETED:
                    continue
                applied = datetime.strptime(w["applyTime"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
                batch.records.append(
                    ExternalRecord(
                        kind="withdrawal",
                        external_id=f"withdrawal:{w['id']}",
                        occurred_at=applied,
                        data={
                            "coin": str(w["coin"]).upper(),
                            "amount": w["amount"],
                            "fee": w.get("transactionFee", "0"),
                            "network": w.get("network"),
                            "tx_id": w.get("txId"),
                        },
                    )
                )
            start = end
        batch.cursor["transfers_since"] = (now - OVERLAP).isoformat()


def _code(response: httpx.Response) -> int | None:
    try:
        body = response.json()
    except ValueError:
        return None
    code = body.get("code") if isinstance(body, dict) else None
    return int(code) if isinstance(code, int) else None


def _message(response: httpx.Response) -> str | None:
    try:
        body = response.json()
    except ValueError:
        return None
    return str(body.get("msg")) if isinstance(body, dict) and body.get("msg") else None
