"""Candles service, analysis API and watchlists."""

from datetime import UTC, datetime
from decimal import Decimal as D

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.market_data import candles as candle_service
from app.modules.market_data import service as market
from app.modules.market_data.models import Cryptocurrency, HistoricalCandle
from app.modules.market_data.providers.binance import (
    BinanceCandleProvider,
    parse_klines,
)
from app.modules.technical_analysis import router as analysis_router
from tests.conftest import API, ClientFactory, Outbox, login, register_verified
from tests.fakes import FakeCandles, FakeProvider, daily_candles, quote


@pytest.fixture
async def assets(db: AsyncSession) -> dict[str, Cryptocurrency]:
    await market.sync_markets(
        db,
        FakeProvider(
            [
                quote("bitcoin", "BTC", 1, "100000"),
                quote("ethereum", "ETH", 2, "3000"),
                quote("tether", "USDT", 3, "1"),
                quote("fake-coin", "FAKE", 4, "2"),
            ]
        ),
    )
    rows = (await db.execute(select(Cryptocurrency))).scalars()
    return {c.source_id: c for c in rows}


def test_binance_parser_rejects_inconsistent_rows_and_flags_live_candle() -> None:
    now = datetime(2026, 1, 2, tzinfo=UTC)
    ms = int(datetime(2026, 1, 1, tzinfo=UTC).timestamp() * 1000)
    rows = [
        [ms, "10", "12", "9", "11", "5", ms + 3_599_999, "55"],
        [ms + 3_600_000, "11", "10", "9", "11.5", "5", ms + 7_199_999, "55"],  # high < close
        [
            int(now.timestamp() * 1000),
            "11",
            "12",
            "10",
            "11",
            "1",
            int(now.timestamp() * 1000) + 3_599_999,
            "11",
        ],
    ]
    candles = parse_klines(rows, now=now)
    assert [c.close for c in candles] == [D("11"), D("11")]
    assert [c.closed for c in candles] == [True, False]
    assert BinanceCandleProvider(client=httpx.AsyncClient()).pair_for("usdt") is None


async def test_candles_are_cached_persisted_and_served_when_provider_fails(
    db: AsyncSession, assets: dict[str, Cryptocurrency]
) -> None:
    provider = FakeCandles({"BTCUSDT": daily_candles(60, D(100000))})
    first = await candle_service.get_candles(db, assets["bitcoin"], "1d", provider)
    assert len(first.candles) == 61 and first.is_stale is False
    await candle_service.get_candles(db, assets["bitcoin"], "1d", provider)
    assert provider.calls == 1  # second read served from cache
    assert await db.scalar(select(func.count()).select_from(HistoricalCandle)) == 60  # closed only

    from app.core.redis import get_redis

    await get_redis().delete(f"candles:{assets['bitcoin'].id}:1d")
    fallback = await candle_service.get_candles(db, assets["bitcoin"], "1d", FakeCandles(fail=True))
    assert fallback.is_stale is True and len(fallback.candles) == 60


async def test_mismatched_or_missing_pairs_are_rejected(
    db: AsyncSession, assets: dict[str, Cryptocurrency]
) -> None:
    # A "FAKEUSDT" market at 50 while the asset trades at 2: a different token with the same ticker.
    provider = FakeCandles({"FAKEUSDT": daily_candles(60, D(50))})
    with pytest.raises(candle_service.CandlesUnavailableError):
        await candle_service.get_candles(db, assets["fake-coin"], "1d", provider)
    with pytest.raises(candle_service.CandlesUnavailableError):
        await candle_service.get_candles(db, assets["tether"], "1d", provider)
    with pytest.raises(candle_service.CandlesUnavailableError):
        await candle_service.get_candles(db, assets["ethereum"], "1d", provider)
    calls = provider.calls
    # Negative results are cached: no repeated upstream calls.
    with pytest.raises(candle_service.CandlesUnavailableError):
        await candle_service.get_candles(db, assets["ethereum"], "1d", provider)
    assert provider.calls == calls


@pytest.fixture
async def authed(client: httpx.AsyncClient, outbox: Outbox) -> httpx.AsyncClient:
    await register_verified(client, outbox)
    await login(client)
    return client


async def test_analysis_endpoint(
    authed: httpx.AsyncClient, assets: dict[str, Cryptocurrency], monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeCandles({"BTCUSDT": daily_candles(250, D(100000))})
    monkeypatch.setattr(analysis_router, "BinanceCandleProvider", lambda: fake)
    response = await authed.get(f"{API}/market/assets/bitcoin/analysis", params={"timeframe": "1d"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["candles"]) == 251
    assert len(body["indicators"]["ema200"]) == 251
    assert body["indicators"]["rsi"][-1] is None  # live candle: no indicator value
    assert body["snapshot"]["rsi"] is not None
    assert body["trend"]["classification"] == "uptrend"
    assert body["trend"]["criteria"]
    assert body["quote"] == "USDT" and body["methodology_version"]

    assert (await authed.get(f"{API}/market/assets/tether/analysis")).status_code == 404
    assert (
        await authed.get(f"{API}/market/assets/bitcoin/analysis", params={"timeframe": "2h"})
    ).status_code == 422


async def test_watchlists_flow_and_isolation(
    authed: httpx.AsyncClient,
    assets: dict[str, Cryptocurrency],
    client_factory: ClientFactory,
    outbox: Outbox,
) -> None:
    lists = (await authed.get(f"{API}/watchlists")).json()
    assert len(lists) == 1 and lists[0]["name"] == "Favoritos" and lists[0]["is_default"]
    fav = lists[0]["id"]
    btc, eth = str(assets["bitcoin"].id), str(assets["ethereum"].id)

    assert (await authed.put(f"{API}/watchlists/{fav}/assets/{btc}")).status_code == 204
    assert (
        await authed.put(f"{API}/watchlists/{fav}/assets/{btc}")
    ).status_code == 204  # idempotent
    listing = (await authed.get(f"{API}/market/assets", params={"watchlist_id": fav})).json()
    assert [a["slug"] for a in listing["items"]] == ["bitcoin"]

    created = await authed.post(f"{API}/watchlists", json={"name": "  Layer   1 "})
    assert created.status_code == 201 and created.json()["name"] == "Layer 1"
    assert (await authed.post(f"{API}/watchlists", json={"name": "Layer 1"})).status_code == 409
    other_list = created.json()["id"]
    await authed.put(f"{API}/watchlists/{other_list}/assets/{eth}")
    assert (await authed.delete(f"{API}/watchlists/{fav}")).status_code == 400  # default stays

    mallory = await client_factory()
    await register_verified(mallory, outbox, email="mallory@example.com", name="Mallory")
    await login(mallory, email="mallory@example.com")
    assert (await mallory.put(f"{API}/watchlists/{fav}/assets/{eth}")).status_code == 404
    assert (
        await mallory.get(f"{API}/market/assets", params={"watchlist_id": fav})
    ).status_code == 404

    assert (await authed.delete(f"{API}/watchlists/{fav}/assets/{btc}")).status_code == 204
    lists = {w["name"]: w for w in (await authed.get(f"{API}/watchlists")).json()}
    assert lists["Favoritos"]["asset_ids"] == []
    assert lists["Layer 1"]["asset_ids"] == [eth]
