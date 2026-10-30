"""Read-only exchange connections: Binance client, key validation, sync, import, reconciliation."""

import hashlib
import hmac
from collections.abc import Sequence
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal as D
from typing import Any
from urllib.parse import parse_qsl, urlsplit

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.exchange_connections import router as connections_router
from app.modules.exchange_connections import service as exchanges
from app.modules.exchange_connections.connectors import binance as binance_module
from app.modules.exchange_connections.connectors.base import (
    ConnectorAuthError,
    ExternalRecord,
    Permissions,
    SyncBatch,
)
from app.modules.exchange_connections.connectors.binance import BinanceConnector
from app.modules.exchange_connections.models import ExchangeConnection, ExchangeRecord
from app.modules.market_data import service as market
from app.modules.market_data.providers.base import Candle
from app.modules.portfolio.models import Transaction
from tests.conftest import API, ClientFactory, Outbox, login, register_verified
from tests.fakes import FakeCandles, FakeFxHistory, FakeProvider, quote

KEY, SECRET = "k" * 64, "s" * 64
NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)


# --------------------------------------------------------------------------- Binance client


class FakeBinance:
    """Minimal Binance REST double that verifies every signature like the real API."""

    def __init__(self, restrictions: dict[str, Any] | None = None) -> None:
        self.restrictions = restrictions or {"enableReading": True, "enableWithdrawals": False}
        self.trades: dict[str, list[dict[str, Any]]] = {}
        self.deposits: list[dict[str, Any]] = []
        self.withdrawals: list[dict[str, Any]] = []
        self.calls: list[tuple[str, dict[str, str]]] = []
        self.auth_error = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = urlsplit(str(request.url))
        raw = url.query
        params = dict(parse_qsl(raw))
        self.calls.append((url.path, params))
        if "signature" in params:
            unsigned = raw.rsplit("&signature=", 1)[0]
            expected = hmac.new(SECRET.encode(), unsigned.encode(), hashlib.sha256).hexdigest()
            assert params["signature"] == expected, "bad signature"
            assert request.headers["X-MBX-APIKEY"] == KEY
            if self.auth_error:
                return httpx.Response(401, json={"code": -2015, "msg": "Invalid API-key"})
        match url.path:
            case "/sapi/v1/account/apiRestrictions":
                return httpx.Response(200, json=self.restrictions)
            case "/api/v3/account":
                return httpx.Response(
                    200,
                    json={
                        "balances": [
                            {"asset": "BTC", "free": "0.4", "locked": "0.1"},
                            {"asset": "XYZ", "free": "0", "locked": "0"},
                        ]
                    },
                )
            case "/api/v3/exchangeInfo":
                symbols = [
                    ("BTCBRL", "BTC", "BRL"),
                    ("BTCUSDT", "BTC", "USDT"),
                    ("ETHBTC", "ETH", "BTC"),
                    ("SOLBRL", "SOL", "BRL"),
                ]
                return httpx.Response(
                    200,
                    json={
                        "symbols": [
                            {"symbol": s, "baseAsset": b, "quoteAsset": q} for s, b, q in symbols
                        ]
                    },
                )
            case "/api/v3/myTrades":
                rows = [
                    t
                    for t in self.trades.get(params["symbol"], [])
                    if t["id"] >= int(params["fromId"])
                ]
                return httpx.Response(200, json=rows[: int(params["limit"])])
            case "/sapi/v1/capital/deposit/hisrec":
                lo, hi = int(params["startTime"]), int(params["endTime"])
                return httpx.Response(
                    200, json=[d for d in self.deposits if lo <= d["insertTime"] < hi]
                )
            case "/sapi/v1/capital/withdraw/history":
                return httpx.Response(
                    200,
                    json=self.withdrawals
                    if params["startTime"] < str(int(NOW.timestamp() * 1000))
                    else [],
                )
        return httpx.Response(404, json={"code": -1, "msg": "not found"})


def _trade(i: int, buyer: bool = True) -> dict[str, Any]:
    time_ms = int(NOW.timestamp() * 1000) - 86400000 * (10 - i)
    return {
        "id": i, "orderId": 100 + i, "price": "300000", "qty": "0.01", "quoteQty": "3000",
        "commission": "0.00001", "commissionAsset": "BTC", "time": time_ms,
        "isBuyer": buyer, "isMaker": False, "isBestMatch": True,
    }  # fmt: skip


def _client(fake: FakeBinance) -> BinanceConnector:
    return BinanceConnector(
        KEY,
        SECRET,
        base_url="https://binance.test",
        transport=httpx.MockTransport(fake),
        now=lambda: NOW,
        backoff_seconds=0,
    )


async def test_permissions_flag_anything_beyond_reading() -> None:
    fake = FakeBinance(
        {
            "enableReading": True,
            "enableWithdrawals": True,
            "enableSpotAndMarginTrading": False,
            "enableFixReadOnly": True,
            "enableNewThing": True,
            "ipRestrict": False,
        }
    )
    perms = await _client(fake).permissions()
    assert perms.can_read and not perms.read_only
    assert perms.write_permissions == ["enableNewThing", "enableWithdrawals"]  # unknown → write


async def test_ip_restricted_read_only_key_is_accepted() -> None:
    """Restricting a key to known IPs makes it safer; it must not count as a write grant."""
    fake = FakeBinance({"enableReading": True, "enableWithdrawals": False, "ipRestrict": True})
    perms = await _client(fake).permissions()
    assert perms.can_read and perms.read_only and perms.write_permissions == []


async def test_balances_and_auth_errors() -> None:
    fake = FakeBinance()
    assert await _client(fake).balances() == {"BTC": D("0.5")}
    fake.auth_error = True
    with pytest.raises(ConnectorAuthError):
        await _client(fake).permissions()


async def test_history_is_incremental_paged_and_filters_unfinished_transfers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(binance_module, "PAGE", 2)
    fake = FakeBinance()
    fake.trades["BTCBRL"] = [_trade(i) for i in range(1, 6)]
    day_ms = int((NOW - timedelta(days=20)).timestamp() * 1000)
    fake.deposits = [
        {
            "id": "d1",
            "coin": "SOL",
            "amount": "10",
            "status": 1,
            "insertTime": day_ms,
            "txId": "0xabc",
        },
        {
            "id": "d2",
            "coin": "SOL",
            "amount": "5",
            "status": 0,
            "insertTime": day_ms,
            "txId": "0xdef",
        },
    ]
    fake.withdrawals = [
        {
            "id": "w1",
            "coin": "BTC",
            "amount": "0.1",
            "transactionFee": "0.0002",
            "status": 6,
            "applyTime": "2026-09-20 08:30:00",
        },
        {
            "id": "w2",
            "coin": "BTC",
            "amount": "0.2",
            "transactionFee": "0.0002",
            "status": 4,
            "applyTime": "2026-09-21 08:30:00",
        },
    ]
    client = _client(fake)
    batch = await client.history({}, ["BTC"])
    kinds = [(r.kind, r.external_id) for r in batch.records]
    assert ("deposit", "deposit:d1") in kinds and (
        "deposit",
        "deposit:d2",
    ) not in kinds  # pending skipped
    assert ("withdrawal", "withdrawal:w1") in kinds and ("withdrawal", "withdrawal:w2") not in kinds
    trades = [r for r in batch.records if r.kind == "trade"]
    assert [r.external_id for r in trades] == [f"trade:BTCBRL:{i}" for i in range(1, 6)]  # 3 pages
    assert trades[0].data["side"] == "buy" and trades[0].data["commission_asset"] == "BTC"
    queried = {p["symbol"] for path, p in fake.calls if path == "/api/v3/myTrades"}
    assert queried == {
        "BTCBRL",
        "BTCUSDT",
        "SOLBRL",
    }  # BTC from balances, SOL from a deposit; ETHBTC never
    windows = [p for path, p in fake.calls if path == "/sapi/v1/capital/deposit/hisrec"]
    assert len(windows) == 5  # 365 days in windows of at most 89
    assert all(int(p["endTime"]) - int(p["startTime"]) <= 89 * 86400000 for p in windows)
    assert batch.cursor["trades"]["BTCBRL"] == 6

    fake.calls.clear()
    fake.trades["BTCBRL"].append(_trade(6))
    again = await client.history(batch.cursor, ["BTC"])
    assert [r.external_id for r in again.records if r.kind == "trade"] == ["trade:BTCBRL:6"]
    assert (
        len([1 for path, _ in fake.calls if path == "/sapi/v1/capital/deposit/hisrec"]) == 1
    )  # 3-day overlap


# --------------------------------------------------------------------------- service

TODAY = datetime.now(UTC).date()


def at(days_ago: int, hour: int = 12) -> datetime:
    return datetime.combine(TODAY - timedelta(days=days_ago), time(hour), UTC)


class FakeConnector:
    exchange_id = "binance"

    def __init__(self, state: dict[str, Any]) -> None:
        self.state = state

    async def permissions(self) -> Permissions:
        return Permissions(True, list(self.state.get("writes", [])))

    async def balances(self) -> dict[str, D]:
        return dict(self.state["balances"])

    async def history(self, cursor: dict[str, Any], assets: Sequence[str]) -> SyncBatch:
        self.state.setdefault("seen_assets", []).append(sorted(assets))
        return SyncBatch(records=list(self.state["records"]), cursor={"n": cursor.get("n", 0) + 1})

    async def aclose(self) -> None:
        return None


def trade(
    i: int,
    days_ago: int,
    side: str,
    qty: str,
    price: str,
    quote: str = "BRL",
    commission: str = "0",
    asset: str = "BTC",
) -> ExternalRecord:
    return ExternalRecord(
        "trade",
        f"trade:BTC{quote}:{i}",
        at(days_ago),
        {
            "symbol": f"BTC{quote}", "base": "BTC", "quote": quote, "side": side,
            "qty": qty, "price": price, "quote_qty": str(D(qty) * D(price)),
            "commission": commission, "commission_asset": asset, "order_id": i,
        },
    )  # fmt: skip


def _daily(closes: dict[int, str]) -> list[Candle]:
    out = []
    for days_ago in sorted(closes, reverse=True):
        c = D(closes[days_ago])
        t = datetime.combine(TODAY - timedelta(days=days_ago), time(), UTC)
        out.append(Candle(t, c, c, c, c, D(1), D(1), True))
    return out


@pytest.fixture
async def exchange_user(
    client: httpx.AsyncClient, outbox: Outbox, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> tuple[httpx.AsyncClient, dict[str, Any]]:
    provider = FakeProvider(
        [
            quote("bitcoin", "BTC", 1, "60000"),
            quote("tether", "USDT", 3, "1"),
            quote("binancecoin", "BNB", 4, "600"),
        ],
        rate="5.0",
    )
    await market.sync_markets(db, provider)
    await market.sync_fx(db, provider)
    state: dict[str, Any] = {"balances": {}, "records": []}
    monkeypatch.setattr(
        connections_router, "connector_factory", lambda: lambda *_: FakeConnector(state)
    )
    await register_verified(client, outbox)
    await login(client)
    return client, state


async def _sync(db: AsyncSession, connection_id: str, state: dict[str, Any]) -> None:
    import uuid

    fx = FakeFxHistory({TODAY - timedelta(days=n): D("5") for n in range(0, 40)})
    candles = FakeCandles({"BTCUSDT": _daily({n: "60000" for n in range(1, 40)})})
    await exchanges.sync(db, uuid.UUID(connection_id), lambda *_: FakeConnector(state), candles, fx)


async def test_only_read_only_keys_are_accepted(
    exchange_user: tuple[httpx.AsyncClient, dict[str, Any]], db: AsyncSession
) -> None:
    client, state = exchange_user
    body = {"exchange_id": "binance", "api_key": KEY, "api_secret": SECRET}
    state["writes"] = ["enableSpotAndMarginTrading", "enableWithdrawals"]
    rejected = await client.post(f"{API}/exchange-connections", json=body)
    assert rejected.status_code == 422
    assert "enableWithdrawals" in rejected.json()["error"]["message"]
    assert await db.scalar(select(func.count()).select_from(ExchangeConnection)) == 0

    state["writes"] = []
    created = await client.post(f"{API}/exchange-connections", json=body)
    assert created.status_code == 201, created.text
    out = created.json()
    assert out["key_hint"] == KEY[-4:] and "api_key" not in out and out["write_permissions"] == []
    stored = (await db.execute(select(ExchangeConnection))).scalar_one()
    assert KEY not in stored.api_key_encrypted and SECRET not in stored.api_secret_encrypted
    assert (await client.post(f"{API}/exchange-connections", json=body)).status_code == 409


async def test_sync_imports_dedupes_reviews_and_reconciles(
    exchange_user: tuple[httpx.AsyncClient, dict[str, Any]],
    db: AsyncSession,
    client_factory: ClientFactory,
    outbox: Outbox,
) -> None:
    client, state = exchange_user
    conn = (
        await client.post(
            f"{API}/exchange-connections",
            json={"exchange_id": "binance", "api_key": KEY, "api_secret": SECRET},
        )
    ).json()
    state["records"] = [
        ExternalRecord(
            "deposit",
            "deposit:d1",
            at(30),
            {"coin": "BTC", "amount": "0.5", "network": "BTC", "tx_id": "0x1"},
        ),
        trade(
            1, 20, "buy", "0.1", "300000", commission="0.0001", asset="BTC"
        ),  # BRL buy, fee in BTC
        trade(
            2, 10, "sell", "0.2", "61000", quote="USDT", commission="0.01", asset="BNB"
        ),  # no BNB → review
        trade(
            3, 8, "sell", "0.1", "62000", quote="USDT", commission="1", asset="USDT"
        ),  # BTC→USDT conversion
        ExternalRecord(
            "withdrawal", "withdrawal:w1", at(5), {"coin": "BTC", "amount": "0.05", "fee": "0.0002"}
        ),
        ExternalRecord(
            "deposit",
            "deposit:d2",
            at(400),
            {"coin": "BTC", "amount": "1", "network": "BTC", "tx_id": "0x2"},
        ),  # no price
    ]
    # Exchange balances after the importable records: BTC 0.5+0.1−0.0001−0.1−0.05−0.0002
    state["balances"] = {"BTC": D("0.4497"), "USDT": D("6199"), "BNB": D("0.5")}
    await _sync(db, conn["id"], state)

    detail = (await client.get(f"{API}/exchange-connections/{conn['id']}")).json()
    assert detail["status"] == "active" and detail["last_synced_at"]
    assert (detail["imported"], detail["needs_review"]) == (4, 2)
    review = {
        r["external_id"]: r
        for r in (await client.get(f"{API}/exchange-connections/{conn['id']}/records")).json()
    }
    assert set(review) == {"trade:BTCUSDT:2", "deposit:d2"}
    assert "Saldo insuficiente de BNB" in review["trade:BTCUSDT:2"]["reason"]
    assert "Sem preço histórico" in review["deposit:d2"]["reason"]

    txs = {t.external_id: t for t in (await db.execute(select(Transaction))).scalars()}
    assert txs["deposit:d1"].unit_price == D("60000") and txs["deposit:d1"].quote_currency == "USD"
    assert txs["trade:BTCBRL:1"].type == "buy" and txs["trade:BTCBRL:1"].quote_currency == "BRL"
    assert txs["trade:BTCBRL:1:fee"].type == "fee" and txs["trade:BTCBRL:1:fee"].quantity == D(
        "0.0001"
    )
    conversion = txs["trade:BTCUSDT:3"]
    assert conversion.type == "conversion" and conversion.to_quantity == D("6200")
    assert txs["withdrawal:w1:fee"].quantity == D("0.0002")
    assert all(t.source == "binance" and t.exchange_id == "binance" for t in txs.values())

    rec = {r["symbol"]: r for r in detail["reconciliation"]["assets"]}
    assert rec["BTC"]["status"] == "ok" and D(rec["BTC"]["voryn"]) == D("0.4497")
    assert rec["USDT"]["status"] == "ok"  # 6200 − 1 fee
    assert rec["BNB"]["status"] == "divergent" and D(rec["BNB"]["difference"]) == D("0.5")
    assert detail["reconciliation"]["ok"] is False

    # Second sync: same records again → nothing duplicated; cursor advanced.
    await _sync(db, conn["id"], state)
    assert await db.scalar(select(func.count()).select_from(Transaction)) == len(txs)
    assert await db.scalar(select(func.count()).select_from(ExchangeRecord)) == 6
    stored = (await db.execute(select(ExchangeConnection))).scalar_one()
    await db.refresh(stored)
    assert stored.sync_cursor["n"] == 2 and "BTC" in stored.sync_cursor["assets"]

    other = await client_factory()
    await register_verified(other, outbox, email="outra@example.com")
    await login(other, email="outra@example.com")
    assert (await other.get(f"{API}/exchange-connections/{conn['id']}")).status_code == 404
    assert (await other.get(f"{API}/exchange-connections/{conn['id']}/records")).status_code == 404
    assert (await other.post(f"{API}/exchange-connections/{conn['id']}/sync")).status_code == 404
    assert (await other.delete(f"{API}/exchange-connections/{conn['id']}")).status_code == 404
    assert (await other.get(f"{API}/exchange-connections")).json() == []

    assert (await client.delete(f"{API}/exchange-connections/{conn['id']}")).status_code == 204
    assert await db.scalar(select(func.count()).select_from(ExchangeRecord)) == 0
    assert await db.scalar(select(func.count()).select_from(Transaction)) == len(
        txs
    )  # history kept


async def test_key_that_gains_write_permission_is_blocked(
    exchange_user: tuple[httpx.AsyncClient, dict[str, Any]], db: AsyncSession
) -> None:
    client, state = exchange_user
    conn = (
        await client.post(
            f"{API}/exchange-connections",
            json={"exchange_id": "binance", "api_key": KEY, "api_secret": SECRET},
        )
    ).json()
    state["writes"] = ["enableWithdrawals"]
    await _sync(db, conn["id"], state)
    detail = (await client.get(f"{API}/exchange-connections/{conn['id']}")).json()
    assert detail["status"] == "blocked" and "enableWithdrawals" in detail["last_error"]
    assert await db.scalar(select(func.count()).select_from(ExchangeRecord)) == 0
    assert (
        await client.post(f"{API}/exchange-connections/{conn['id']}/sync")
    ).status_code == 429  # just created
