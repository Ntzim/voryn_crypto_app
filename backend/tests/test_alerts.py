"""Alert conditions (edge semantics), CRUD, evaluation, dedupe, cooldown and notifications."""

from datetime import timedelta
from decimal import Decimal as D

import httpx
import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.alerts import conditions
from app.modules.alerts import service as alerts
from app.modules.alerts.models import Alert, AlertType, Notification
from app.modules.market_data import service as market
from app.modules.market_data.models import Cryptocurrency, MarketTicker
from tests.conftest import API, ClientFactory, Outbox, login, register_verified
from tests.fakes import FakeCandles, FakeProvider, daily_candles, quote

Obs = conditions.Observation


def test_price_alert_fires_only_on_crossing() -> None:
    params = {"target": "100", "currency": "USD"}
    state, event = conditions.evaluate(
        AlertType.PRICE_ABOVE, params, Obs("BTC", price=D(120)), None
    )
    assert state == {"met": True} and event is None  # baseline: no immediate fire
    state, event = conditions.evaluate(
        AlertType.PRICE_ABOVE, params, Obs("BTC", price=D(90)), state
    )
    assert event is None
    state, event = conditions.evaluate(
        AlertType.PRICE_ABOVE, params, Obs("BTC", price=D(101)), state
    )
    assert event is not None and "ultrapassou US$ 100,00" in event.title
    _, event = conditions.evaluate(AlertType.PRICE_ABOVE, params, Obs("BTC", price=D(105)), state)
    assert event is None  # still above: no repeat


def test_ma_cross_respects_direction() -> None:
    params = {"fast": 50, "slow": 200, "direction": "up"}
    below = Obs("BTC", candle_time="t1", ema={50: D(90), 200: D(100)})
    above = Obs("BTC", candle_time="t2", ema={50: D(110), 200: D(100)})
    state, _ = conditions.evaluate(AlertType.MA_CROSS, params, below, None)
    state, event = conditions.evaluate(AlertType.MA_CROSS, params, above, state)
    assert event is not None and "acima" in event.body
    state, event = conditions.evaluate(AlertType.MA_CROSS, params, below, state)
    assert event is None  # downward cross ignored for direction=up


def test_volume_spike_fires_once_per_candle() -> None:
    params = {"ratio": "2"}
    state, _ = conditions.evaluate(
        AlertType.VOLUME_SPIKE, params, Obs("ETH", candle_time="c0", volume_ratio=D(1)), None
    )
    state, event = conditions.evaluate(
        AlertType.VOLUME_SPIKE, params, Obs("ETH", candle_time="c1", volume_ratio=D(3)), state
    )
    assert event is not None
    state, event = conditions.evaluate(
        AlertType.VOLUME_SPIKE, params, Obs("ETH", candle_time="c1", volume_ratio=D(3)), state
    )
    assert event is None
    _, event = conditions.evaluate(
        AlertType.VOLUME_SPIKE, params, Obs("ETH", candle_time="c2", volume_ratio=D("2.5")), state
    )
    assert event is not None


def test_signal_change_with_target_and_missing_data() -> None:
    params = {"to": "buy_potential"}
    state, _ = conditions.evaluate(
        AlertType.SIGNAL_CHANGE, params, Obs("SOL", candle_time="a", signal="neutral"), None
    )
    state, event = conditions.evaluate(
        AlertType.SIGNAL_CHANGE, params, Obs("SOL", candle_time="b", signal="attention"), state
    )
    assert event is None  # change, but not to the requested classification
    state, event = conditions.evaluate(
        AlertType.SIGNAL_CHANGE,
        params,
        Obs("SOL", candle_time="c", signal="buy_potential", signal_score=D(71)),
        state,
    )
    assert event is not None and "score 71" in event.body and "não recomendações" in event.body
    assert conditions.evaluate(AlertType.SIGNAL_CHANGE, params, Obs("SOL"), state) == (None, None)


# --------------------------------------------------------------------------- API + evaluation


@pytest.fixture
async def setup(client: httpx.AsyncClient, outbox: Outbox, db: AsyncSession) -> dict[str, str]:
    await market.sync_markets(
        db,
        FakeProvider([quote("bitcoin", "BTC", 1, "100000"), quote("ethereum", "ETH", 2, "3000")]),
    )
    await register_verified(client, outbox)
    await login(client)
    rows = (await db.execute(select(Cryptocurrency.source_id, Cryptocurrency.id))).all()
    return {slug: str(i) for slug, i in rows}


async def test_alert_validation_and_isolation(
    client: httpx.AsyncClient, setup: dict[str, str], client_factory: ClientFactory, outbox: Outbox
) -> None:
    bad = [
        {"type": "price_above", "asset_id": setup["bitcoin"], "params": {}},
        {"type": "price_above", "params": {"target": "1"}},  # missing asset
        {"type": "rsi_below", "asset_id": setup["bitcoin"], "params": {"level": "150"}},
        {"type": "ma_cross", "asset_id": setup["bitcoin"], "params": {"fast": 200, "slow": 50}},
        {
            "type": "price_above",
            "asset_id": setup["bitcoin"],
            "params": {"target": "1"},
            "cooldown_minutes": 1,
        },
    ]
    for body in bad:
        assert (await client.post(f"{API}/alerts", json=body)).status_code == 422, body

    created = await client.post(
        f"{API}/alerts",
        json={"type": "rsi_below", "asset_id": setup["bitcoin"], "params": {"level": "30"}},
    )
    assert created.status_code == 201
    alert = created.json()
    assert alert["timeframe"] == "1d" and alert["description"] == "BTC · RSI abaixo de 30 · 1d"

    eve = await client_factory()
    await register_verified(eve, outbox, email="eve@example.com", name="Eve")
    await login(eve, email="eve@example.com")
    assert (await eve.get(f"{API}/alerts")).json() == []
    assert (await eve.delete(f"{API}/alerts/{alert['id']}")).status_code == 404


async def test_price_alert_evaluation_dedupe_cooldown_and_email(
    client: httpx.AsyncClient, setup: dict[str, str], db: AsyncSession, outbox: Outbox
) -> None:
    body = {
        "type": "price_above",
        "asset_id": setup["bitcoin"],
        "params": {"target": "105000", "currency": "USD"},
        "cooldown_minutes": 60,
    }
    assert (await client.post(f"{API}/alerts", json=body)).status_code == 201
    provider = FakeCandles({})

    async def set_price(value: str) -> None:
        await db.execute(
            update(MarketTicker)
            .where(MarketTicker.cryptocurrency_id == setup["bitcoin"])
            .values(price=D(value), fetched_at=market.utcnow())
        )
        await db.commit()

    assert await alerts.evaluate_all(db, provider) == 0  # baseline below target
    await set_price("106000")
    sent_before = len(outbox)
    assert await alerts.evaluate_all(db, provider) == 1
    assert len(outbox) == sent_before + 1 and "ultrapassou" in outbox[-1].subject
    assert await alerts.evaluate_all(db, provider) == 0  # still above: no repeat

    # Dip and cross again within the cooldown: suppressed.
    await set_price("100000")
    await alerts.evaluate_all(db, provider)
    await set_price("107000")
    assert await alerts.evaluate_all(db, provider) == 0
    assert await db.scalar(select(func.count()).select_from(Notification)) == 1

    # Stale quotes are never used.
    await db.execute(update(MarketTicker).values(fetched_at=market.utcnow() - timedelta(hours=2)))
    await db.execute(update(Alert).values(last_triggered_at=None, last_state={"met": False}))
    await db.commit()
    assert await alerts.evaluate_all(db, provider) == 0

    listing = (await client.get(f"{API}/notifications")).json()
    assert listing["unread"] == 1 and listing["items"][0]["data"]["asset_slug"] == "bitcoin"
    nid = listing["items"][0]["id"]
    assert (await client.post(f"{API}/notifications/{nid}/read")).status_code == 204
    assert (await client.get(f"{API}/notifications")).json()["unread"] == 0


async def test_indicator_alert_uses_closed_candles(
    client: httpx.AsyncClient, setup: dict[str, str], db: AsyncSession
) -> None:
    # Steadily rising candles → RSI near 100; an "RSI above 70" alert should fire on crossing.
    body = {
        "type": "rsi_above",
        "asset_id": setup["bitcoin"],
        "timeframe": "1d",
        "params": {"level": "70"},
        "notify_email": False,
    }
    alert_id = (await client.post(f"{API}/alerts", json=body)).json()["id"]
    await db.execute(update(Alert).where(Alert.id == alert_id).values(last_state={"met": False}))
    await db.commit()
    provider = FakeCandles({"BTCUSDT": daily_candles(250, D(100000))})
    assert await alerts.evaluate_all(db, provider) == 1
    item = (await client.get(f"{API}/notifications")).json()["items"][0]
    assert item["title"] == "RSI de BTC acima de 70"
