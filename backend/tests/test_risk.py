"""Risk statistics (hand-checked values), scenario rules and the risk API."""

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal as D

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.market_data import service as market
from app.modules.market_data.models import Cryptocurrency
from app.modules.market_data.providers.base import Candle
from app.modules.portfolio import router as portfolio_router
from app.modules.risk import metrics as m
from app.modules.risk.scenario import Exposure, simulate
from app.modules.technical_analysis import router as analysis_router
from tests.conftest import API, ClientFactory, Outbox, login, register_verified
from tests.fakes import FakeCandles, FakeFxHistory, FakeProvider, quote

DAY0 = date(2026, 1, 1)


def series(values: list[str | int]) -> list[tuple[date, D]]:
    return [(DAY0 + timedelta(days=i), D(v)) for i, v in enumerate(values)]


# --------------------------------------------------------------------------- statistics


def test_volatility_is_sample_stdev_annualized_over_365_days() -> None:
    returns = [D("0.01"), D("-0.01")] * 20
    expected = D("0.01") * (D(40) / D(39)).sqrt() * D(365).sqrt() * 100
    assert m.annualized_volatility_pct(returns) == expected
    assert m.annualized_volatility_pct(returns[:29]) is None  # below the minimum sample


def test_historical_var_and_expected_shortfall_use_the_empirical_tail() -> None:
    returns = [D(i - 50) / 1000 for i in range(100)]  # −0.050 … +0.049
    assert m.historical_var(returns, D("0.95")) == D("0.046")  # 5th worst day
    assert m.historical_var(returns, D("0.99")) == D("0.050")  # worst day
    assert m.expected_shortfall(returns, D("0.95")) == D("0.048")  # mean of the 5 worst


def test_var_is_never_negative() -> None:
    assert m.historical_var([D("0.01")] * 40, D("0.95")) == 0


def test_max_drawdown_finds_peak_trough_and_current_level() -> None:
    dd = m.max_drawdown(series([100, 120, 90, 110, 60, 96]))
    assert dd.pct == D(-50)
    assert (dd.peak, dd.trough) == (DAY0 + timedelta(days=1), DAY0 + timedelta(days=4))
    assert dd.current_pct == D(-20)


def test_worst_window_is_the_worst_change_between_points_n_days_apart() -> None:
    w = m.worst_window(series([100, 110, 99, 88, 120]), 2)
    assert w is not None and w.pct == D(-20)
    assert (w.start, w.end) == (DAY0 + timedelta(days=1), DAY0 + timedelta(days=3))


def test_beta_and_correlation_of_a_leveraged_copy() -> None:
    market_returns = [D("0.03") if i % 3 == 0 else D("-0.01") for i in range(60)]
    asset = [r * 2 for r in market_returns]
    assert m.beta(asset, market_returns).quantize(D("1e-20")) == 2  # type: ignore[union-attr]
    rho = m.correlation(asset, market_returns)
    assert rho is not None and abs(rho - 1) < D("1e-20")


def test_aligned_keeps_only_common_days() -> None:
    days, values = m.aligned(
        {"a": {DAY0: D(1), DAY0 + timedelta(days=1): D(2)}, "b": {DAY0 + timedelta(days=1): D(3)}}
    )
    assert days == [DAY0 + timedelta(days=1)] and values == {"a": [D(2)], "b": [D(3)]}


def test_hhi() -> None:
    assert m.hhi([D("0.5"), D("0.5")]) == D("0.5")
    assert m.hhi([D(1)]) == 1


# --------------------------------------------------------------------------- scenario


def test_scenario_propagates_btc_by_beta_and_respects_overrides() -> None:
    lines = simulate(
        [
            Exposure("btc", D(1000), None, is_btc=True, is_stablecoin=False),
            Exposure("eth", D(500), D("1.5"), is_btc=False, is_stablecoin=False),
            Exposure("usdt", D(200), None, is_btc=False, is_stablecoin=True),
            Exposure("new", D(100), None, is_btc=False, is_stablecoin=False),
            Exposure("lev", D(100), D(4), is_btc=False, is_stablecoin=False),
            Exposure("sol", D(100), D(1), is_btc=False, is_stablecoin=False),
        ],
        D(-30),
        {"sol": D(10)},
    )
    by_key = {ln.key: ln for ln in lines}
    assert by_key["btc"].new_value == D(700)
    assert (by_key["eth"].change_pct, by_key["eth"].method) == (D("-45.0"), "beta")
    assert by_key["usdt"].pnl == 0 and by_key["usdt"].method == "stablecoin"
    assert by_key["new"].method == "assumed_beta_1" and by_key["new"].change_pct == -30
    assert by_key["lev"].change_pct == -100 and by_key["lev"].new_value == 0  # floor at zero
    assert (by_key["sol"].change_pct, by_key["sol"].method) == (D(10), "override")


# --------------------------------------------------------------------------- API

TODAY = datetime.now(UTC).date()
N_DAYS = 120


def _candles(closes: list[D]) -> list[Candle]:
    start = datetime.combine(TODAY - timedelta(days=len(closes)), time(), UTC)
    return [
        Candle(start + timedelta(days=i), c, c, c, c, D(1000), D(50_000_000), True)
        for i, c in enumerate(closes)
    ]


def _path(start: D, returns: list[D]) -> list[D]:
    out = [start]
    for r in returns:
        out.append(out[-1] * (1 + r))
    return out


BTC_RETURNS = [D("0.03") if i % 3 == 0 else D("-0.01") for i in range(N_DAYS - 1)]
BTC_CLOSES = _path(D(100000), BTC_RETURNS)
ETH_CLOSES = _path(D(3000), [r * 2 for r in BTC_RETURNS])


@pytest.fixture
async def risk_user(
    client: httpx.AsyncClient,
    outbox: Outbox,
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[httpx.AsyncClient, str, dict[str, str]]:
    provider = FakeProvider(
        [
            quote("bitcoin", "BTC", 1, str(BTC_CLOSES[-1])),
            quote("ethereum", "ETH", 2, str(ETH_CLOSES[-1])),
            quote("tether", "USDT", 3, "1"),
        ],
        rate="5.0",
    )
    await market.sync_markets(db, provider)
    await market.sync_fx(db, provider)
    ptax = FakeFxHistory({TODAY - timedelta(days=n): D("5") for n in range(1, 10)})
    monkeypatch.setattr(portfolio_router, "BcbPtaxProvider", lambda: ptax)
    candles = FakeCandles({"BTCUSDT": _candles(BTC_CLOSES), "ETHUSDT": _candles(ETH_CLOSES)})
    monkeypatch.setattr(analysis_router, "BinanceCandleProvider", lambda: candles)
    ids = {
        slug: str(i)
        for slug, i in (await db.execute(select(Cryptocurrency.source_id, Cryptocurrency.id))).all()
    }

    await register_verified(client, outbox)
    await login(client)
    pid = (await client.get(f"{API}/portfolios")).json()[0]["id"]
    executed = datetime.combine(TODAY - timedelta(days=2), time(12), UTC).isoformat()
    for slug, qty, price in (
        ("bitcoin", "0.5", BTC_CLOSES[-1]),
        ("ethereum", "5", ETH_CLOSES[-1]),
        ("tether", "5000", D(1)),
    ):
        response = await client.post(
            f"{API}/portfolios/{pid}/transactions",
            json={
                "type": "buy",
                "asset_id": ids[slug],
                "quantity": qty,
                "unit_price": str(price.quantize(D("0.01"))),
                "quote_currency": "USD",
                "executed_at": executed,
            },
        )
        assert response.status_code == 201, response.text
    return client, pid, ids


async def test_risk_report(risk_user: tuple[httpx.AsyncClient, str, dict[str, str]]) -> None:
    client, pid, _ = risk_user
    response = await client.get(
        f"{API}/portfolios/{pid}/risk", params={"currency": "USD", "window": 90}
    )
    assert response.status_code == 200, response.text
    r = response.json()
    assert r["window_days"] == 90 and r["observations"] == 90
    assert D(r["coverage_pct"]) == 100 and r["uncovered_assets"] == []
    assert r["period_end"] == (TODAY - timedelta(days=1)).isoformat()
    assert D(r["volatility_pct"]) > 0 and D(r["drawdown"]["pct"]) < 0
    var95, var99 = r["var"]
    assert 0 < D(var95["pct"]) <= D(var99["pct"])
    expected = D(r["covered_value"]) * D(var95["pct"]) / 100
    assert abs(D(var95["amount"]) - expected) < D(r["covered_value"]) / 10000
    assets = {a["asset"]["symbol"]: a for a in r["assets"]}
    assert D(assets["BTC"]["beta_btc"]) == 1
    assert D(assets["ETH"]["beta_btc"]) == D("2.00")
    assert assets["USDT"]["is_stablecoin"] and assets["USDT"]["liquidity"] == "high"
    assert D(assets["USDT"]["risk_contribution_pct"]) == 0
    contributions = sum((D(a["risk_contribution_pct"]) for a in r["assets"]), D(0))
    assert abs(contributions - 100) < 1
    assert r["correlation"]["symbols"] == ["BTC", "ETH"]  # by value, stablecoins excluded
    assert D(r["correlation"]["values"][0][1]) == D("1.00")
    assert {s["days"] for s in r["stress"]} == {7, 30}
    flags = {f["id"] for f in r["flags"]}
    assert "stablecoins" in flags
    assert r["data_source"].startswith("Binance") and r["methodology"]


async def test_scenario_and_isolation(
    risk_user: tuple[httpx.AsyncClient, str, dict[str, str]],
    client_factory: ClientFactory,
    outbox: Outbox,
) -> None:
    client, pid, ids = risk_user
    response = await client.post(
        f"{API}/portfolios/{pid}/risk/scenario",
        params={"currency": "USD"},
        json={"btc_change_pct": "-10", "window": 90},
    )
    assert response.status_code == 200, response.text
    s = response.json()
    lines = {ln["asset"]["symbol"]: ln for ln in s["lines"]}
    assert D(lines["BTC"]["change_pct"]) == -10 and lines["BTC"]["method"] == "beta"
    assert D(lines["ETH"]["change_pct"]) == -20
    assert D(lines["USDT"]["change_pct"]) == 0 and lines["USDT"]["method"] == "stablecoin"
    assert D(s["pnl"]) == sum(D(ln["pnl"]) for ln in s["lines"])

    override = await client.post(
        f"{API}/portfolios/{pid}/risk/scenario",
        params={"currency": "USD"},
        json={
            "btc_change_pct": "-10",
            "overrides": [{"asset_id": ids["ethereum"], "change_pct": "5"}],
        },
    )
    assert {ln["asset"]["symbol"]: ln["method"] for ln in override.json()["lines"]}[
        "ETH"
    ] == "override"
    bad = await client.post(
        f"{API}/portfolios/{pid}/risk/scenario", json={"btc_change_pct": "-150"}
    )
    assert bad.status_code == 422

    other = await client_factory()
    await register_verified(other, outbox, email="outra@example.com")
    await login(other, email="outra@example.com")
    assert (await other.get(f"{API}/portfolios/{pid}/risk")).status_code == 404
