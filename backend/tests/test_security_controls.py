"""Regression tests for the security controls, by the scenarios of the security mission.

Covered elsewhere (kept there, next to the feature):
1. Financial isolation: test_portfolio_api.test_portfolios_are_isolated and the
   *_isolation tests of each module; here, the audit of denied access.
4. Stale data: test_signal_quality.
6. Rate limiting: test_auth (login, 2FA per account); here, the 429 path and its event.
7. Authentication: test_authorization (every route without a session).
"""

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security_events
from app.core.redis import get_redis
from app.modules.audit import service as audit
from app.modules.audit.models import AuditLog
from app.modules.exchange_connections import router as connections_router
from app.modules.exchange_connections import service as exchanges
from app.modules.exchange_connections.connectors.base import ConnectorError
from app.modules.exchange_connections.connectors.binance import BinanceConnector
from app.modules.exchange_connections.models import ExchangeConnection
from app.modules.market_data import service as market
from tests.conftest import API, PASSWORD, ClientFactory, Outbox, login, register_verified
from tests.fakes import FakeCandles, FakeFxHistory, FakeProvider, quote
from tests.test_exchange_connections import (  # noqa: F401  (fixture)
    KEY,
    SECRET,
    FakeBinance,
    FakeConnector,
    exchange_user,
)

CONNECT = {"exchange_id": "binance", "label": "Principal", "api_key": KEY, "api_secret": SECRET}


async def _actions(db: AsyncSession, action: str) -> list[AuditLog]:
    return list((await db.execute(select(AuditLog).where(AuditLog.action == action))).scalars())


# --------------------------------------------------------------------------- 1. isolation


async def test_reaching_another_users_resource_is_audited_but_looks_missing(
    client: httpx.AsyncClient, client_factory: ClientFactory, outbox: Outbox, db: AsyncSession
) -> None:
    await register_verified(client, outbox)
    await login(client)
    watchlist = (await client.post(f"{API}/watchlists", json={"name": "Minha"})).json()
    portfolio_id = (await client.get(f"{API}/portfolios")).json()[0]["id"]

    eve = await client_factory()
    await register_verified(eve, outbox, email="eve@example.com", name="Eve")
    await login(eve, email="eve@example.com")
    foreign = await eve.patch(f"{API}/watchlists/{watchlist['id']}", json={"name": "x"})
    missing = await eve.patch(f"{API}/watchlists/{uuid.uuid4()}", json={"name": "x"})
    # Same answer either way: ids cannot be probed.
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json()["error"]["message"] == missing.json()["error"]["message"]
    assert (await eve.get(f"{API}/portfolios/{portfolio_id}/summary")).status_code == 404

    denied = await _actions(db, "authz.access_denied")
    assert {d.context["resource"] for d in denied} == {"watchlists", "portfolios"}  # not the miss
    eve_id = (await eve.get(f"{API}/me")).json()["id"]
    assert all(str(d.user_id) == eve_id and d.context["request_id"] for d in denied)
    assert (await client.get(f"{API}/watchlists")).json()[-1]["name"] == "Minha"


async def test_owner_cannot_be_reassigned_through_the_request_body(
    client: httpx.AsyncClient, client_factory: ClientFactory, outbox: Outbox, db: AsyncSession
) -> None:
    await register_verified(client, outbox)
    await login(client)
    eve = await client_factory()
    await register_verified(eve, outbox, email="eve@example.com", name="Eve")
    await login(eve, email="eve@example.com")
    eve_id = (await eve.get(f"{API}/me")).json()["id"]

    created = await client.post(
        f"{API}/watchlists", json={"name": "Minha", "user_id": eve_id, "id": str(uuid.uuid4())}
    )
    assert created.status_code == 201
    assert len((await eve.get(f"{API}/watchlists")).json()) == 1  # only Eve's default list


# --------------------------------------------------------------------------- 2. credentials


async def test_no_endpoint_ever_returns_exchange_credentials(
    exchange_user: tuple[httpx.AsyncClient, dict[str, Any]],  # noqa: F811
    db: AsyncSession,
) -> None:
    client, state = exchange_user
    created = await client.post(f"{API}/exchange-connections", json=CONNECT)
    assert created.status_code == 201
    cid = created.json()["id"]
    state["writes"] = ["enableWithdrawals"]  # next sync blocks it: error paths too
    await exchanges.sync(
        db, uuid.UUID(cid), lambda *_: FakeConnector(state), FakeCandles(), FakeFxHistory({})
    )
    bodies = [
        created.text,
        (await client.get(f"{API}/exchange-connections")).text,
        (await client.get(f"{API}/exchange-connections/{cid}")).text,
        (await client.get(f"{API}/exchange-connections/{cid}/records")).text,
    ]
    for body in bodies:
        assert KEY not in body and SECRET not in body
        assert KEY[:16] not in body and SECRET[:16] not in body
    assert json.loads(bodies[2])["key_hint"] == KEY[-4:]
    stored = (await db.execute(select(ExchangeConnection))).scalar_one()
    assert KEY not in stored.api_key_encrypted and SECRET not in stored.api_secret_encrypted
    for entry in (await db.execute(select(AuditLog))).scalars():
        assert KEY not in json.dumps(entry.context) and SECRET not in json.dumps(entry.context)


# --------------------------------------------------------------------------- 3. integrations


class FailingConnector(FakeConnector):
    async def balances(self) -> dict[str, Any]:
        raise ConnectorError("Erro da Binance: Service unavailable.")


async def test_a_failing_exchange_affects_only_its_connection(
    db: AsyncSession,
    client_factory: ClientFactory,
    outbox: Outbox,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await market.sync_markets(db, FakeProvider([quote("bitcoin", "BTC", 1, "60000")]))
    conns = {}
    for name in ("ana", "bia"):
        c = await client_factory()
        await register_verified(c, outbox, email=f"{name}@example.com", name=name.title())
        await login(c, email=f"{name}@example.com")
        conns[name] = c
    state: dict[str, Any] = {"balances": {}, "records": []}
    monkeypatch.setattr(
        connections_router, "connector_factory", lambda: lambda *_: FakeConnector(state)
    )
    ids = {}
    for name, c in conns.items():
        body = {**CONNECT, "api_key": KEY + name, "api_secret": SECRET + name}
        ids[name] = (await c.post(f"{API}/exchange-connections", json=body)).json()["id"]

    def factory(_: str, key: str, __: str) -> FakeConnector:
        return FailingConnector(state) if key.endswith("ana") else FakeConnector(state)

    for name in ids:
        await exchanges.sync(db, uuid.UUID(ids[name]), factory, FakeCandles(), FakeFxHistory({}))

    ana = (await conns["ana"].get(f"{API}/exchange-connections/{ids['ana']}")).json()
    bia = (await conns["bia"].get(f"{API}/exchange-connections/{ids['bia']}")).json()
    assert ana["status"] == "error" and bia["status"] == "active"
    assert ana["last_error"] == "Erro da Binance: Service unavailable."  # user-facing text only
    failed = await _actions(db, "exchange.sync_failed")
    assert [f.context["connection_id"] for f in failed] == [ids["ana"]]


def _binance(handler: Any) -> BinanceConnector:
    return BinanceConnector(
        KEY, SECRET, base_url="https://binance.test", transport=httpx.MockTransport(handler),
        backoff_seconds=0,
    )  # fmt: skip


async def test_transient_exchange_errors_are_retried_with_backoff() -> None:
    calls: list[int] = []
    good = FakeBinance()

    def flaky(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(503) if len(calls) < 3 else good(request)

    assert (await _binance(flaky).permissions()).read_only
    assert len(calls) == 3  # two retries, then success

    calls.clear()

    def always_down(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(502)

    with pytest.raises(ConnectorError):
        await _binance(always_down).permissions()
    assert len(calls) == 3


async def test_rate_limited_answers_are_not_retried() -> None:
    calls: list[int] = []

    def limited(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(429, json={"code": -1003, "msg": "Too many requests"})

    with pytest.raises(ConnectorError, match="Limite de requisições"):
        await _binance(limited).permissions()
    assert len(calls) == 1


@pytest.mark.parametrize(
    "payload",
    [
        {"balances": [{"asset": "BTC"}]},
        {"balances": [{"asset": "BTC", "free": "x", "locked": "0"}]},
    ],
)
async def test_malformed_exchange_payloads_fail_cleanly(payload: dict[str, Any]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    with pytest.raises(ConnectorError) as raised:
        await _binance(handler).balances()
    assert raised.value.message == "A Binance respondeu em um formato inesperado."


# --------------------------------------------------------------------------- 5. parameters


async def test_recommendations_cannot_be_steered_by_the_client(
    client: httpx.AsyncClient, outbox: Outbox, db: AsyncSession
) -> None:
    await market.sync_markets(db, FakeProvider([quote("bitcoin", "BTC", 1, "60000")]))
    await register_verified(client, outbox)
    await login(client)
    # Only the timeframe is a parameter, and it is validated.
    bad = await client.get(f"{API}/signals/bitcoin", params={"timeframe": "1y"})
    assert bad.status_code == 422
    # Scores, weights and strategies have no write endpoint at all.
    for method, path in [
        ("POST", "/signals"),
        ("PUT", "/signals/bitcoin"),
        ("PATCH", "/signals/strategy"),
        ("POST", "/signals/strategy"),
    ]:
        response = await client.request(method, f"{API}{path}", json={"score": 99})
        assert response.status_code in (404, 405), (method, path)
    backtest = await client.post(
        f"{API}/backtests",
        json={"asset_id": str(uuid.uuid4()), "strategy": "x", "params": {"weights": "hack"}},
    )
    assert backtest.status_code == 422


# --------------------------------------------------------------------------- 6. rate limiting


async def test_throttled_requests_answer_429_and_are_counted(client: httpx.AsyncClient) -> None:
    for _ in range(5):
        await client.post(f"{API}/auth/register", json={"email": "x"})  # invalid: not counted
    payload = {"email": "nobody@example.com"}
    statuses = [
        (await client.post(f"{API}/auth/password/forgot", json=payload)).status_code
        for _ in range(6)
    ]
    assert statuses == [202] * 5 + [429]
    counts = await security_events.counts(security_events._bucket())
    assert counts["rate_limited"] == 1


async def test_costly_endpoints_are_limited_per_user_not_per_address(
    client: httpx.AsyncClient, client_factory: ClientFactory, outbox: Outbox
) -> None:
    await register_verified(client, outbox)
    await login(client)
    pid = (await client.get(f"{API}/portfolios")).json()[0]["id"]
    url = f"{API}/portfolios/{pid}/risk/scenario"
    # Invalid bodies still count: the limit protects the server, not the happy path.
    statuses = [(await client.post(url, json={})).status_code for _ in range(31)]
    assert statuses == [422] * 30 + [429]
    assert (await client.post(url, json={})).json()["error"]["details"]["retry_after"] > 0

    # Same address (the test client), different user: unaffected.
    other = await client_factory()
    await register_verified(other, outbox, email="eve@example.com", name="Eve")
    await login(other, email="eve@example.com")
    own = (await other.get(f"{API}/portfolios")).json()[0]["id"]
    assert (await other.post(f"{API}/portfolios/{own}/risk/scenario", json={})).status_code == 422


# --------------------------------------------------------------------------- 8. audit


async def test_security_events_are_audited_without_secrets(
    client: httpx.AsyncClient, outbox: Outbox, db: AsyncSession
) -> None:
    await register_verified(client, outbox)
    wrong = "senha-errada-123"
    await client.post(f"{API}/auth/login", json={"email": "ana@example.com", "password": wrong})
    await login(client)
    new = "outra-frase-longa-e-segura"
    response = await client.post(
        f"{API}/me/password", json={"current_password": PASSWORD, "new_password": new}
    )
    assert response.status_code == 204

    entries = list((await db.execute(select(AuditLog).order_by(AuditLog.id))).scalars())
    actions = [e.action for e in entries]
    for expected in ("auth.login_failed", "auth.login_succeeded", "auth.password_changed"):
        assert expected in actions
    session_token = client.cookies.get("voryn_session") or ""
    for e in entries:
        dumped = json.dumps(e.context)
        for secret in (PASSWORD, wrong, new, session_token):
            assert not secret or secret not in dumped
        assert e.context.get("request_id")  # links the entry to the access log


async def test_audit_trail_is_append_only(db: AsyncSession) -> None:
    await audit.record_now("test.event", user_id=None, detail="x")
    row_id = (await db.execute(select(AuditLog.id))).scalar_one()
    for statement in (
        "UPDATE audit_logs SET action = 'tampered' WHERE id = :id",
        "DELETE FROM audit_logs WHERE id = :id",
    ):
        with pytest.raises(DBAPIError, match="append-only"):
            await db.execute(text(statement), {"id": row_id})
        await db.rollback()
    assert (await db.execute(select(AuditLog.action))).scalar_one() == "test.event"


async def test_account_deletion_anonymises_but_keeps_the_trail(
    client: httpx.AsyncClient, outbox: Outbox, db: AsyncSession
) -> None:
    await register_verified(client, outbox)
    await db.execute(text("DELETE FROM users"))  # SET NULL on audit_logs.user_id is allowed
    await db.commit()
    entries = list((await db.execute(select(AuditLog))).scalars())
    assert entries and all(e.user_id is None for e in entries)


async def test_audit_entries_past_retention_are_pruned(db: AsyncSession) -> None:
    old = datetime.now(UTC) - timedelta(days=400)
    db.add(AuditLog(action="test.old", context={}, created_at=old))
    db.add(AuditLog(action="test.recent", context={}))
    await db.commit()
    assert await audit.prune(db) == 1
    assert list((await db.execute(select(AuditLog.action))).scalars()) == ["test.recent"]


# --------------------------------------------------------------------------- monitoring


async def test_abnormal_event_rates_raise_one_alert_per_hour() -> None:
    previous_window = (security_events._bucket() - 1) * security_events.WINDOW_SECONDS + 1
    redis = get_redis()
    await redis.set(f"secev:access_denied:{security_events._bucket(previous_window)}", 11)
    await redis.set(f"secev:login_failed:{security_events._bucket(previous_window)}", 3)
    sent: list[list[security_events.Alert]] = []

    async def notify(alerts: list[security_events.Alert]) -> None:
        sent.append(alerts)

    alerts = await security_events.check(notify)
    assert [(a.kind, a.count) for a in alerts] == [("access_denied", 11)]  # 3 logins is normal
    assert sent == [alerts]
    assert await security_events.check(notify) == []  # cooldown: no repeat within the hour
