"""Signals are never presented as current or confident when their data is not."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import httpx
import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import get_redis
from app.modules.market_data import service as market
from app.modules.market_data.models import Cryptocurrency, HistoricalCandle
from app.modules.market_data.providers.base import Candle
from app.modules.signals import quality
from app.modules.signals import service as signals
from app.modules.signals.models import AnalysisSignal
from app.modules.technical_analysis import router as analysis_router
from tests.conftest import API, Outbox, login, register_verified
from tests.fakes import FakeCandles, FakeProvider, daily_candles, quote
from tests.test_signals import run, snapshot

NOW = datetime(2026, 6, 1, tzinfo=UTC)
FRESH = timedelta(minutes=15)


def candles(n: int, close: str = "100", volume: str = "10") -> list[Candle]:
    c = D(close)
    return [
        Candle(NOW - timedelta(days=n - i), c, c * D("1.01"), c * D("0.99"), c, D(volume), c, True)
        for i in range(n)
    ]


def assess(closed: list[Candle], **kw: object) -> quality.QualityReport:
    args: dict[str, object] = {
        "closed": closed,
        "snapshot": snapshot(),
        "timeframe": "1d",
        "is_stale": False,
        "quote_price": D(100),
        "quote_fetched_at": NOW,
        "now": NOW,
        "quote_max_age": FRESH,
    }
    args.update(kw)
    return quality.assess(**args)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- grading


def test_consistent_recent_data_is_valid() -> None:
    report = assess(candles(100))
    assert report.status == "valid" and report.reasons == []


def test_stale_wins_over_lesser_problems_and_keeps_every_reason() -> None:
    report = assess(candles(20), is_stale=True)
    assert report.status == "stale"
    assert len(report.reasons) == 2 and "insuficiente" in report.reasons[1]


@pytest.mark.parametrize(
    ("kw", "expected"),
    [
        ({"closed": candles(30)}, "Histórico insuficiente"),
        ({"snapshot": snapshot(rsi=None, atr=None)}, "rsi, atr"),
    ],
)
def test_incomplete_inputs(kw: dict[str, object], expected: str) -> None:
    args: dict[str, object] = {"closed": candles(100), **kw}
    report = assess(**args)  # type: ignore[arg-type]
    assert report.status == "incomplete" and expected in report.reasons[0]


def test_zero_volume_and_impossible_moves_are_anomalous() -> None:
    assert assess(candles(100, volume="0")).status == "anomalous"
    jump = candles(100)
    last = jump[-1]
    jump[-1] = Candle(last.open_time, D(100), D(260), D(99), D(250), D(10), D(2500), True)
    report = assess(jump, quote_price=D(250))
    assert report.status == "anomalous" and "150%" in report.reasons[0]


def test_cross_source_disagreement_is_anomalous_only_with_a_fresh_quote() -> None:
    assert assess(candles(100), quote_price=D(140)).status == "anomalous"  # 29% off on 1d
    assert assess(candles(100), quote_price=D(120)).status == "valid"  # within daily range
    assert assess(candles(100), quote_price=D(108), timeframe="1h").status == "valid"
    assert assess(candles(100), quote_price=D(115), timeframe="1h").status == "anomalous"
    old_quote = NOW - timedelta(hours=1)
    assert assess(candles(100), quote_price=D(140), quote_fetched_at=old_quote).status == "valid"


def test_a_quality_issue_withholds_buy_and_sell() -> None:
    assert run().classification == "buy_potential"
    held = run(quality_issue="Preço diverge 40% da cotação de referência (CoinGecko).")
    assert held.classification == "attention"
    assert held.justification.startswith("Dados inconsistentes ou incompletos — sinal suspenso.")
    assert any("Qualidade dos dados" in r for r in held.risks)


# --------------------------------------------------------------------------- end to end


@pytest.fixture
async def btc(db: AsyncSession) -> Cryptocurrency:
    await market.sync_markets(db, FakeProvider([quote("bitcoin", "BTC", 1, "100000", change="1")]))
    return (await db.execute(select(Cryptocurrency))).scalar_one()


async def _generate(
    db: AsyncSession, crypto: Cryptocurrency, provider: FakeCandles
) -> AnalysisSignal:
    strategy = await signals.active_strategy(db)
    ctx = await signals.market_context(db, provider, "1d")
    return await signals.generate(db, crypto, "1d", provider, strategy, ctx)


async def test_generation_stores_the_grade(db: AsyncSession, btc: Cryptocurrency) -> None:
    signal = await _generate(db, btc, FakeCandles({"BTCUSDT": daily_candles(250, D(100000))}))
    assert signal.data_quality == "valid" and signal.quality_reasons == []


async def test_disagreeing_sources_suspend_the_signal(
    db: AsyncSession, btc: Cryptocurrency
) -> None:
    provider = FakeCandles({"BTCUSDT": daily_candles(250, D(100000))})
    await _generate(db, btc, provider)  # pairs BTCUSDT while both sources agree
    await db.execute(delete(AnalysisSignal))
    await db.commit()
    await get_redis().delete(f"candles:{btc.id}:1d")
    await market.sync_markets(db, FakeProvider([quote("bitcoin", "BTC", 1, "50000", change="1")]))
    signal = await _generate(db, btc, provider)
    assert signal.data_quality == "anomalous"
    assert signal.classification == "attention"
    assert "diverge" in signal.quality_reasons[0]


async def test_short_history_suspends_the_signal(db: AsyncSession, btc: Cryptocurrency) -> None:
    signal = await _generate(db, btc, FakeCandles({"BTCUSDT": daily_candles(40, D(100000))}))
    assert signal.data_quality == "incomplete" and signal.classification == "attention"


async def test_signals_are_never_shown_as_current_when_data_is_not(
    client: httpx.AsyncClient,
    outbox: Outbox,
    db: AsyncSession,
    btc: Cryptocurrency,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeCandles({"BTCUSDT": daily_candles(250, D(100000))})
    monkeypatch.setattr(analysis_router, "BinanceCandleProvider", lambda: fake)
    await register_verified(client, outbox)
    await login(client)
    url = f"{API}/signals/bitcoin"

    current = (await client.get(url, params={"timeframe": "1d"})).json()
    assert current["is_current"] is True and current["data_quality"] == "valid"

    # Provider down, stored candles still there: the same candle was already analysed, so
    # the stored result comes back, but graded by the data read now: stale, not current.
    fake.fail = True
    await get_redis().delete(f"candles:{btc.id}:1d")
    stale = (await client.get(url, params={"timeframe": "1d"})).json()
    assert stale["data_quality"] == "stale" and stale["is_current"] is False
    assert stale["classification"] == current["classification"]  # the record is preserved
    assert "desatualizados" in stale["quality_reasons"][0]

    # No candles at all and the last analysis is weeks old: shown only as history.
    await db.execute(delete(HistoricalCandle))
    await db.execute(
        update(AnalysisSignal).values(candle_time=AnalysisSignal.candle_time - timedelta(days=30))
    )
    await db.commit()
    await get_redis().delete(f"candles:{btc.id}:1d")
    historical = (await client.get(url, params={"timeframe": "1d"})).json()
    assert historical["is_current"] is False
    assert historical["data_quality"] == "unavailable"
    assert "análise histórica" in historical["quality_reasons"][0]

    listing = (await client.get(f"{API}/signals", params={"timeframe": "1d"})).json()
    assert listing["items"] == []  # lists never include historical signals
