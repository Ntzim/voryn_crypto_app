"""Signal engine rules, persistence per candle and API."""

from datetime import UTC, datetime
from decimal import Decimal as D

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.market_data import service as market
from app.modules.market_data.models import Cryptocurrency
from app.modules.signals import engine
from app.modules.signals import service as signals
from app.modules.signals.models import AnalysisSignal
from app.modules.technical_analysis import router as analysis_router
from app.modules.technical_analysis.levels import Level
from app.modules.technical_analysis.schemas import Snapshot
from app.modules.technical_analysis.trend import Classification, Criterion, TrendResult
from tests.conftest import API, Outbox, login, register_verified
from tests.fakes import FakeCandles, FakeProvider, daily_candles, quote

T = datetime(2026, 1, 1, tzinfo=UTC)


def snapshot(**kw: object) -> Snapshot:
    base: dict[str, object] = {
        "as_of": T,
        "close": D(100),
        "rsi": D(52),
        "rsi_state": "neutral",
        "macd": D(1),
        "macd_signal": D("0.5"),
        "macd_hist": D("0.5"),
        "macd_cross": None,
        "macd_cross_bars_ago": None,
        "ema9": D(99),
        "ema21": D(98),
        "ema50": D(95),
        "ema200": D(90),
        "sma20": D(98),
        "bb_upper": D(105),
        "bb_lower": D(95),
        "bb_percent_b": D("0.5"),
        "bb_bandwidth_pct": D(10),
        "atr": D(2),
        "atr_pct": D(2),
        "volume": D(10),
        "volume_ratio": D(1),
        "volatility_annualized_pct": D(40),
    }
    base.update(kw)
    return Snapshot.model_validate(base)


def trend(classification: Classification, score: int, available: int = 6) -> TrendResult:
    return TrendResult(
        classification, score, available, "high", [Criterion("x", "neutral", "x")], "s"
    )


def level(price: str, kind: str) -> Level:
    return Level(D(price), 3, T, kind)


GOOD_MARKET = engine.MarketContext(D(70), "uptrend")
BAD_MARKET = engine.MarketContext(D(20), "downtrend")


def run(**kw: object) -> engine.SignalResult:
    args: dict[str, object] = {
        "snapshot": snapshot(),
        "trend": trend("uptrend", 6),
        "supports": [level("97", "support")],
        "resistances": [level("115", "resistance")],
        "bandwidth_percentile": D(30),
        "last_candle_up": True,
        "market": GOOD_MARKET,
        "stale": False,
    }
    args.update(kw)
    return engine.evaluate(**args)  # type: ignore[arg-type]


def test_aligned_bullish_evidence_is_buy_potential_with_invalidation() -> None:
    result = run(snapshot=snapshot(macd_cross="bullish", volume_ratio=D(2), rsi=D(58)))
    assert result.classification == "buy_potential"
    assert D(65) <= result.score <= D(100)
    assert any("suporte" in i for i in result.invalidation)
    assert any("EMA 50" in i for i in result.invalidation)
    assert sum(c.weight for c in result.components) == 1


def test_weighted_score_is_the_documented_sum() -> None:
    result = run()
    expected = sum((c.score * c.weight for c in result.components), D(0)).quantize(D("0.1"))
    assert result.score == expected


def test_bearish_evidence_is_sell_potential() -> None:
    result = run(
        snapshot=snapshot(rsi=D(40), macd_hist=D(-1), macd_cross="bearish", close=D(100)),
        trend=trend("downtrend", -6),
        last_candle_up=False,
        supports=[level("98", "support")],
        resistances=[level("130", "resistance")],
        market=BAD_MARKET,
    )
    assert result.classification == "sell_potential"
    assert any("resistência" in i for i in result.invalidation)
    assert "Tendência principal de baixa." in result.risks


def test_stale_data_never_produces_buy_or_sell() -> None:
    result = run(snapshot=snapshot(macd_cross="bullish", volume_ratio=D(2)), stale=True)
    assert result.classification == "attention"
    assert result.justification.startswith("Dados desatualizados")
    assert any("desatualizados" in r for r in result.risks)


def test_overbought_extreme_is_attention_and_listed_as_risk() -> None:
    result = run(snapshot=snapshot(rsi=D(80), macd_hist=D("-0.1")), trend=trend("uptrend", 3))
    assert result.classification == "attention"
    assert any("sobrecompra" in r for r in result.risks)


def test_weights_are_configurable() -> None:
    only_market = {k: D(0) for k in engine.COMPONENTS} | {"market": D(1)}
    result = run(weights=only_market, market=engine.MarketContext(D(10), "downtrend"))
    assert result.score == D(20)  # mean of breadth 10 and BTC downtrend 30


# --------------------------------------------------------------------------- persistence & API


@pytest.fixture
async def btc(db: AsyncSession) -> Cryptocurrency:
    await market.sync_markets(db, FakeProvider([quote("bitcoin", "BTC", 1, "100000", change="1")]))
    return (await db.execute(select(Cryptocurrency))).scalar_one()


async def test_signal_is_stored_once_per_closed_candle(
    db: AsyncSession, btc: Cryptocurrency
) -> None:
    provider = FakeCandles({"BTCUSDT": daily_candles(250, D(100000))})
    strategy = await signals.active_strategy(db)
    ctx = await signals.market_context(db, provider, "1d")
    first = await signals.generate(db, btc, "1d", provider, strategy, ctx)
    again = await signals.generate(db, btc, "1d", provider, strategy, ctx)
    assert first.id == again.id
    assert await db.scalar(select(func.count()).select_from(AnalysisSignal)) == 1
    assert first.methodology_version and first.data_source == "binance:BTCUSDT"
    assert first.indicators["rsi"] is not None


async def test_signal_api(
    client: httpx.AsyncClient, outbox: Outbox, btc: Cryptocurrency, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeCandles({"BTCUSDT": daily_candles(250, D(100000))})
    monkeypatch.setattr(analysis_router, "BinanceCandleProvider", lambda: fake)
    await register_verified(client, outbox)
    await login(client)

    one = (await client.get(f"{API}/signals/bitcoin", params={"timeframe": "1d"})).json()
    assert one["asset"]["symbol"] == "BTC"
    assert 0 <= float(one["score"]) <= 100
    assert one["classification"] in {"buy_potential", "neutral", "attention", "sell_potential"}
    assert {c["key"] for c in one["components"]} == set(engine.COMPONENTS)
    assert one["justification"] and one["invalidation"]
    assert one["strategy_version"] == 1

    listing = (await client.get(f"{API}/signals", params={"timeframe": "1d"})).json()
    assert [s["asset"]["slug"] for s in listing["items"]] == ["bitcoin"]
    assert "não é probabilidade" in listing["disclaimer"]
    assert listing["strategy"]["weights_pct"]["trend"] == "25.0"

    history = (await client.get(f"{API}/signals/bitcoin/history")).json()
    assert len(history) == 1
    assert (await client.get(f"{API}/signals/unknown/history")).status_code == 404


def test_micro_cap_prices_keep_significant_digits() -> None:
    assert engine._money(D("0.000005123")) == "US$ 0,000005123"
    assert engine._money(D("0.5")) == "US$ 0,5000"
    assert engine._money(D("74250.5")) == "US$ 74.250,50"


def test_acronyms_survive_sentence_case() -> None:
    result = run(snapshot=snapshot(macd_hist=D(1), rsi=D(60)))
    momentum = next(c for c in result.components if c.key == "momentum")
    assert "MACD" in momentum.detail and "RSI" in momentum.detail


async def test_stablecoins_get_no_signal(db: AsyncSession) -> None:
    await market.sync_markets(db, FakeProvider([quote("usd-coin", "USDC", 7, "1")]))
    usdc = (await db.execute(select(Cryptocurrency))).scalar_one()
    provider = FakeCandles({"USDCUSDT": daily_candles(250, D(1))})
    strategy = await signals.active_strategy(db)
    with pytest.raises(signals.StablecoinError):
        await signals.generate(db, usdc, "1d", provider, strategy, GOOD_MARKET)
    assert usdc.id not in await signals.universe(db)
