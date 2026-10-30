"""Backtester: no look-ahead, next-open execution with costs, train/validation split, API."""

import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.backtesting import engine as bt
from app.modules.backtesting import service as backtests
from app.modules.backtesting.models import BacktestRun
from app.modules.backtesting.strategies import VorynSignal
from app.modules.market_data import service as market
from app.modules.market_data.models import Cryptocurrency
from app.modules.market_data.providers.base import Candle
from app.modules.signals import engine as signal_engine
from tests.conftest import API, ClientFactory, Outbox, login, register_verified
from tests.fakes import FakeCandles, FakeProvider, quote

T0 = datetime(2024, 1, 1, tzinfo=UTC)
NO_COSTS = bt.Costs(D(0), D(0))


def wave(n: int, base: float = 100.0) -> list[Candle]:
    """Deterministic cycles with drift; each open is the previous close (plus a gap)."""
    out: list[Candle] = []
    prev = D(str(base))
    for i in range(n):
        close = D(str(round(base * (1 + 0.25 * math.sin(i / 12)) + i * 0.08, 4)))
        open_ = (prev * D("1.002")).quantize(D("0.0001"))
        high, low = max(open_, close) * D("1.01"), min(open_, close) * D("0.99")
        out.append(
            Candle(T0 + timedelta(days=i), open_, high, low, close, D(100), D(100) * close, True)
        )
        prev = close
    return out


# --------------------------------------------------------------------------- engine


@pytest.mark.parametrize(
    "make",
    [
        lambda: bt.EmaCross(9, 26),
        lambda: bt.MacdCross(12, 26, 9),
        lambda: bt.RsiReversion(35, 65),
        bt.BuyAndHold,
    ],
)
def test_decisions_never_depend_on_future_candles(make: object) -> None:
    candles = wave(240)
    full = make()  # type: ignore[operator]
    full.prepare(candles)
    in_position = False
    for t in range(30, len(candles)):
        truncated = make()  # type: ignore[operator]
        truncated.prepare(candles[: t + 1])
        decision = full.decide(candles, t, in_position)
        assert decision == truncated.decide(candles[: t + 1], t, in_position), t
        in_position = decision


def test_voryn_signal_decisions_never_depend_on_future_candles() -> None:
    candles = wave(260)
    weights, thresholds = signal_engine.DEFAULT_WEIGHTS, signal_engine.DEFAULT_THRESHOLDS
    full = VorynSignal("1d", weights, thresholds, 1, None)
    for t in (205, 230, 259):
        truncated = VorynSignal("1d", weights, thresholds, 1, None)
        assert full.classification(candles, t) == truncated.classification(candles[: t + 1], t)


def test_fills_happen_at_the_next_open_with_slippage_and_fees() -> None:
    candles = wave(50)
    costs = bt.Costs(fee_bps=D(10), slippage_bps=D(20))
    run = bt.simulate(candles, bt.BuyAndHold(), 5, 50, costs)
    buy_price = candles[6].open * (1 + D("0.002"))
    qty = bt.INITIAL_CAPITAL / (buy_price * D("1.001"))
    trade = run.trades[0]
    assert trade.entry_time == candles[6].open_time  # decided on candle 5, filled on 6's open
    assert trade.entry_price == buy_price and trade.quantity == qty
    assert run.fees == qty * buy_price * D("0.001")
    assert run.equity[0] == (candles[5].open_time, bt.INITIAL_CAPITAL)  # flat on decision bar
    assert run.equity[-1][1] == qty * candles[49].close
    assert run.trades[0].exit_time is None  # still open at the end of the segment


def test_exit_pays_costs_and_records_the_round_trip() -> None:
    candles = wave(60)

    class OneTrade(bt.Strategy):
        def decide(self, candles: object, t: int, in_position: bool) -> bool:
            return 10 <= t < 20

    costs = bt.Costs(fee_bps=D(10), slippage_bps=D(10))
    run = bt.simulate(candles, OneTrade(), 0, 60, costs)
    trade = run.trades[0]
    assert trade.entry_time == candles[11].open_time and trade.exit_time == candles[21].open_time
    sell = candles[21].open * D("0.999")
    assert trade.exit_price == sell
    assert trade.proceeds == trade.quantity * sell * D("0.999")
    assert run.equity[-1][1] == trade.proceeds  # back in cash after the exit


def test_metrics() -> None:
    run = bt.Run(
        equity=[(T0 + timedelta(days=i), D(v)) for i, v in enumerate([10000, 12000, 9000, 11000])],
        exposure=[False, True, True, False],
    )
    m = bt.metrics(run, "1d")
    assert m.total_return_pct == 10 and m.max_drawdown_pct == -25
    assert m.exposure_pct == 50 and m.sharpe is None  # too few observations
    assert m.profit_factor is None  # no closed trades


def test_profit_factor_is_gross_gains_over_gross_losses() -> None:
    run = bt.Run(equity=[(T0, D(10000))], exposure=[False])
    run.trades = [
        bt.Trade(T0, D(1), D(1), D(100), T0, D(1), D(130)),  # +30
        bt.Trade(T0, D(1), D(1), D(100), T0, D(1), D(90)),  # −10
        bt.Trade(T0, D(1), D(1), D(100), T0, D(1), D(95)),  # −5
    ]
    m = bt.metrics(run, "1d")
    assert m.profit_factor == 2 and m.win_rate_pct is not None and m.trades == 3


def test_optimization_uses_train_only_and_validation_runs_once() -> None:
    candles = wave(400)
    grid = [{"fast": f, "slow": s} for f in (5, 9) for s in (20, 40)]
    body = backtests.backtest(
        candles, "1d", lambda p: bt.EmaCross(p["fast"], p["slow"]), {}, grid, NO_COSTS, 70
    )
    assert body["warmup"] == 40  # the longest warm-up of the grid, for every candidate
    selected = [g for g in body["grid"] if g["selected"]]
    assert len(selected) == 1 and selected[0]["params"] == body["selected_params"]
    best = max(body["grid"], key=lambda g: D(g["train_sharpe"] or "-1e9"))
    assert best["selected"]
    split = datetime.fromisoformat(body["split_at"])
    assert all(
        datetime.fromisoformat(t["entry_time"]) > split
        for t in body["trades"]
        if t["segment"] == "validation"
    )
    validation = [p for p in body["equity"] if p["segment"] == "validation"]
    assert D(validation[0]["strategy"]) == bt.INITIAL_CAPITAL  # starts flat with fresh capital


def test_short_history_is_refused() -> None:
    with pytest.raises(backtests.BacktestInputError):
        backtests.backtest(wave(150), "1d", lambda _: bt.EmaCross(12, 50), {}, [], NO_COSTS, 70)


# --------------------------------------------------------------------------- API


@pytest.fixture
async def bt_user(
    client: httpx.AsyncClient, outbox: Outbox, db: AsyncSession
) -> tuple[httpx.AsyncClient, dict[str, str]]:
    await market.sync_markets(
        db,
        FakeProvider(
            [
                quote("bitcoin", "BTC", 1, str(wave(600)[-1].close)),
                quote("ethereum", "ETH", 2, str(wave(600, 50.0)[-1].close)),
                quote("tether", "USDT", 3, "1"),
            ]
        ),
    )
    ids = {
        s: str(i)
        for s, i in (await db.execute(select(Cryptocurrency.source_id, Cryptocurrency.id))).all()
    }
    await register_verified(client, outbox)
    await login(client)
    return client, ids


async def _execute(db: AsyncSession, run_id: str) -> None:
    import uuid

    candles = FakeCandles({"BTCUSDT": wave(600), "ETHUSDT": wave(600, 50.0)})
    await backtests.execute(db, uuid.UUID(run_id), candles)


async def test_backtest_lifecycle(
    bt_user: tuple[httpx.AsyncClient, dict[str, str]], db: AsyncSession
) -> None:
    client, ids = bt_user
    catalogue = (await client.get(f"{API}/backtests/strategies")).json()
    assert {s["key"] for s in catalogue} == {
        "voryn_signal",
        "ema_cross",
        "macd_cross",
        "rsi_reversion",
        "buy_and_hold",
    }

    response = await client.post(
        f"{API}/backtests",
        json={
            "asset_id": ids["ethereum"],
            "strategy": "ema_cross",
            "optimize": True,
            "fee_bps": "10",
            "slippage_bps": "5",
        },
    )
    assert response.status_code == 202, response.text
    queued = response.json()
    assert queued["status"] == "queued" and queued["params"] == {"fast": 12, "slow": 50}

    await _execute(db, queued["id"])
    done = (await client.get(f"{API}/backtests/{queued['id']}")).json()
    assert done["status"] == "done", done["error"]
    result = done["result"]
    assert result["data_source"] == "binance:ETHUSDT" and result["candles"] == 600
    assert len(result["grid"]) == 9 and sum(g["selected"] for g in result["grid"]) == 1
    assert result["validation"]["benchmark"]["trades"] == 1
    assert any("sem uso de dados futuros" in n for n in result["notes"])
    listing = (await client.get(f"{API}/backtests")).json()
    assert listing[0]["id"] == queued["id"]
    assert (
        listing[0]["validation_return_pct"] == result["validation"]["strategy"]["total_return_pct"]
    )

    assert (await client.delete(f"{API}/backtests/{queued['id']}")).status_code == 204
    assert (await client.get(f"{API}/backtests/{queued['id']}")).status_code == 404


async def test_voryn_signal_backtest_runs(
    bt_user: tuple[httpx.AsyncClient, dict[str, str]], db: AsyncSession
) -> None:
    client, ids = bt_user
    run = (
        await client.post(
            f"{API}/backtests",
            json={"asset_id": ids["ethereum"], "strategy": "voryn_signal", "train_pct": 60},
        )
    ).json()
    await _execute(db, run["id"])
    done = (await client.get(f"{API}/backtests/{run['id']}")).json()
    assert done["status"] == "done", done["error"]
    assert done["result"]["selected_params"] == {"strategy": "voryn-core", "version": 1}
    assert any("tendência do Bitcoin" in n for n in done["result"]["notes"])


async def test_invalid_requests_and_isolation(
    bt_user: tuple[httpx.AsyncClient, dict[str, str]],
    db: AsyncSession,
    client_factory: ClientFactory,
    outbox: Outbox,
) -> None:
    client, ids = bt_user
    bad = [
        {"asset_id": ids["tether"], "strategy": "buy_and_hold"},
        {"asset_id": ids["bitcoin"], "strategy": "ema_cross", "params": {"fast": 50, "slow": 20}},
        {"asset_id": ids["bitcoin"], "strategy": "ema_cross", "params": {"period": 3}},
        {"asset_id": ids["bitcoin"], "strategy": "rsi_reversion", "train_pct": 95},
    ]
    for body in bad:
        assert (await client.post(f"{API}/backtests", json=body)).status_code == 422, body

    run = (
        await client.post(
            f"{API}/backtests", json={"asset_id": ids["bitcoin"], "strategy": "buy_and_hold"}
        )
    ).json()
    other = await client_factory()
    await register_verified(other, outbox, email="outra@example.com")
    await login(other, email="outra@example.com")
    assert (await other.get(f"{API}/backtests/{run['id']}")).status_code == 404
    assert (await other.get(f"{API}/backtests")).json() == []


async def test_provider_failure_marks_the_run_failed(
    bt_user: tuple[httpx.AsyncClient, dict[str, str]], db: AsyncSession
) -> None:
    import uuid

    client, ids = bt_user
    run = (
        await client.post(
            f"{API}/backtests", json={"asset_id": ids["bitcoin"], "strategy": "buy_and_hold"}
        )
    ).json()
    await backtests.execute(db, uuid.UUID(run["id"]), FakeCandles(fail=True))
    failed = (await client.get(f"{API}/backtests/{run['id']}")).json()
    assert failed["status"] == "failed" and failed["error"]
    stored = (await db.execute(select(BacktestRun))).scalar_one()
    assert stored.finished_at is not None
