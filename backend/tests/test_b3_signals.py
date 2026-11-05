"""B3 signals: FII fundamentals in the score, partial sessions excluded, crypto untouched."""

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.redis import get_redis
from app.modules.market_data import calendars, exchanges, service
from app.modules.market_data.providers.brapi import BrapiProvider, FiiFundamentals, FiiPayment
from app.modules.signals import b3
from app.modules.signals import service as signals
from app.modules.signals.models import AnalysisSignal
from tests.conftest import API, Outbox, login, register_verified
from tests.fakes import FakeProvider, quote

SP = ZoneInfo("America/Sao_Paulo")
# During the session: the 28th is partial, so the last closed session is the 27th.
NOW = datetime(2026, 10, 28, 14, 0, tzinfo=SP)
LAST_CLOSED = date(2026, 10, 27)
BASE = f"{API}/market/exchanges/B3"


def _ticker(symbol: str, price: float, sub_type: str = "stock") -> dict[str, Any]:
    return {
        "symbol": symbol,
        "name": f"{symbol} SA",
        "subType": sub_type,
        "currency": "BRL",
        "isActive": True,
        "quote": {"lastPrice": price, "changePercent": 1, "volume": 5_000_000, "marketCap": 10**9},
    }


def _bars(end: date, count: int, start_price: float, step: float) -> list[dict[str, Any]]:
    days: list[date] = []
    day = end
    while len(days) < count:
        if calendars.is_trading_day("B3", day):
            days.append(day)
        day -= timedelta(days=1)
    rows = []
    for i, current in enumerate(reversed(days)):
        close = start_price + step * i
        stamp = datetime.combine(current, time(13), UTC)
        rows.append(
            {
                "date": int(stamp.timestamp()),
                "open": close - step / 2,
                "high": close + 0.5,
                "low": close - step - 0.5,
                "close": close,
                "volume": 1_000_000 + i * 1000,
                "adjustedClose": close,
            }
        )
    rows.reverse()  # brapi returns newest first
    return rows


class Upstream:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.bars = 70
        self.indicators_status = 200
        self.history_status = 200
        self.headers: dict[str, str] = {}
        self.nav = 100.0
        self.as_of = "2026-09-01 00:00:00+00"
        self.months = 12

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/v2")
        if path == "/tickers":
            rows = [
                _ticker("PETR4", 75),
                _ticker("BOVA11", 165, "etf"),
                _ticker("HGLG11", 90, "fii"),
            ]
            return httpx.Response(200, json={"results": rows, "pagination": {"hasNextPage": False}})
        symbol = request.url.params["symbols"]
        self.calls.append(f"{path}:{symbol}")
        if path == "/stocks/historical":
            if self.history_status != 200:
                return httpx.Response(
                    self.history_status, headers=self.headers, json={"error": True}
                )
            # Includes the partial bar of the 28th with an absurd price: it must be ignored.
            bars = _bars(LAST_CLOSED, self.bars, 40, 0.5)
            stamp = int(datetime.combine(NOW.date(), time(13), UTC).timestamp())
            partial = {
                "date": stamp,
                "open": 500,
                "high": 500,
                "low": 500,
                "close": 500,
                "volume": 1,
            }
            return httpx.Response(
                200,
                json={"results": [{"data": {"historicalDataPrice": [partial, *bars]}}]},
            )
        if path == "/fii/indicators":
            if self.indicators_status != 200:
                return httpx.Response(
                    self.indicators_status, json={"error": True, "code": "FORBIDDEN"}
                )
            row = {
                "symbol": symbol,
                "navPerShare": self.nav,
                "priceToNav": 1.5,  # brapi's ratio uses an old price: must not be used
                "dividendYield12m": 0.09,
                "asOfDate": self.as_of,
                "segmentType": "tijolo",
            }
            return httpx.Response(200, json={"fiis": [row]})
        if path == "/fii/dividends":
            rows = [
                {
                    "label": "RENDIMENTO",
                    "rate": 0.9,
                    "paymentDate": f"{date(2026, 10, 15) - timedelta(days=30 * i)}T03:00:00.000Z",
                }
                for i in range(self.months)
            ]
            # An amortization returns capital: it does not count as yield.
            rows.append(
                {"label": "AMORTIZACAO", "rate": 50, "paymentDate": "2026-09-20T03:00:00.000Z"}
            )
            return httpx.Response(200, json={"dividends": rows})
        return httpx.Response(404, json={"error": True})


def _provider(upstream: Upstream) -> BrapiProvider:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(upstream), base_url="https://brapi.test/api"
    )
    return BrapiProvider(client=client, max_attempts=1)


@pytest.fixture
async def upstream(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> Upstream:
    monkeypatch.setattr(get_settings(), "markets_enabled", ["CRYPTO", "B3"])
    monkeypatch.setattr(get_settings(), "brapi_token", None)
    monkeypatch.setattr(exchanges, "utcnow", lambda: NOW)
    fake = Upstream()
    await service.sync_markets(db, FakeProvider([quote("bitcoin", "BTC", 1, "65000")]))
    assert await exchanges.sync_b3(db, _provider(fake)) == 3
    fake.calls.clear()
    return fake


async def _signal(db: AsyncSession, asset_type: str = "FII") -> Any:
    listing = await b3.list_signals(db, asset_type)  # type: ignore[arg-type]
    assert len(listing.items) == 1
    return listing.items[0]


async def test_signals_cover_stocks_and_fiis_with_their_own_components(
    db: AsyncSession, upstream: Upstream
) -> None:
    assert await b3.generate(db, _provider(upstream)) == 2

    stock = await _signal(db, "STOCK")
    assert stock.asset.symbol == "PETR4"
    assert {c.key for c in stock.components} == {
        "trend",
        "momentum",
        "volume",
        "volatility",
        "levels",
        "market",
    }
    assert stock.fundamentals is None
    assert "somente técnica" in stock.scope

    fii = await _signal(db)
    assert fii.asset.symbol == "HGLG11"
    by_key = {c.key: c for c in fii.components}
    assert {"valuation", "income"} <= set(by_key)
    assert sum(c.weight_pct for c in fii.components) == pytest.approx(
        Decimal(100), abs=Decimal("0.5")
    )
    assert by_key["income"].weight_pct > by_key["trend"].weight_pct

    # P/VP on today's price, not brapi's stale ratio.
    assert fii.fundamentals is not None
    assert fii.fundamentals.price_to_nav == Decimal("0.9")
    assert "P/VP de 0,90" in by_key["valuation"].detail
    # 12 payments of 0,90 on R$ 90: 12%. The amortization of R$ 50 does not count.
    assert fii.fundamentals.dividend_yield_12m == Decimal(12)
    assert fii.fundamentals.months_paid_12m == 12
    assert by_key["income"].score == Decimal(80)
    assert by_key["valuation"].score == Decimal(70)
    assert fii.fundamentals.segment == "tijolo"


async def test_partial_session_is_excluded_and_money_is_in_reais(
    db: AsyncSession, upstream: Upstream
) -> None:
    await b3.generate(db, _provider(upstream))
    stock = await _signal(db, "STOCK")
    assert stock.candle_time.date() == LAST_CLOSED
    assert stock.reference_price < 100  # the partial bar closes at 500
    text = " ".join([stock.justification, *stock.risks, *stock.invalidation])
    text += " ".join(c.detail for c in stock.components)
    assert "US$" not in text
    assert "Bitcoin" not in text
    assert stock.is_current is True
    assert stock.data_source == "brapi:PETR4"


async def test_right_after_the_close_the_day_is_still_partial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "brapi_plan", "free")
    just_closed = datetime(2026, 10, 28, 17, 10, tzinfo=SP)
    assert b3.closed_day(just_closed, 1800) == LAST_CLOSED
    assert b3.closed_day(just_closed + timedelta(minutes=30), 1800) == date(2026, 10, 28)


async def test_rerun_for_the_same_session_makes_no_requests(
    db: AsyncSession, upstream: Upstream
) -> None:
    assert await b3.generate(db, _provider(upstream)) == 2
    upstream.calls.clear()
    assert await b3.generate(db, _provider(upstream)) == 0
    assert upstream.calls == []


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"indicators_status": 403}, "plano de dados"),
        ({"indicators_status": 404}, "patrimonial"),
        ({"as_of": "2026-01-01 00:00:00+00"}, "desatualizado"),
    ],
)
async def test_missing_or_old_fundamentals_suspend_buy_and_sell(
    db: AsyncSession, upstream: Upstream, change: dict[str, Any], reason: str
) -> None:
    for key, value in change.items():
        setattr(upstream, key, value)
    await b3.generate(db, _provider(upstream))
    fii = await _signal(db)
    assert fii.classification == "attention"
    assert fii.data_quality == "incomplete"
    assert any(reason in r for r in fii.quality_reasons)


async def test_plan_refusal_costs_one_request_and_ranks_below_complete_data(
    db: AsyncSession, upstream: Upstream
) -> None:
    upstream.indicators_status = 403
    await b3.generate(db, _provider(upstream))
    assert "/fii/dividends:HGLG11" not in upstream.calls
    fii = await _signal(db)
    assert fii.fundamentals is not None
    assert fii.fundamentals.price_to_nav is None


async def test_volatility_text_states_the_real_window(db: AsyncSession, upstream: Upstream) -> None:
    await b3.generate(db, _provider(upstream))
    stock = await _signal(db, "STOCK")
    volatility = next(c for c in stock.components if c.key == "volatility")
    assert "últimos 100 candles" not in volatility.detail
    assert "últimos 51 candles" in volatility.detail  # 70 closed bars minus the 19 of warm-up


async def test_too_little_history_suspends_buy_and_sell(
    db: AsyncSession, upstream: Upstream
) -> None:
    upstream.bars = 40
    await b3.generate(db, _provider(upstream))
    stock = await _signal(db, "STOCK")
    assert stock.classification == "attention"
    assert stock.data_quality == "incomplete"


async def test_rate_limit_stops_the_run_and_blocks_the_account(
    db: AsyncSession, upstream: Upstream
) -> None:
    upstream.history_status = 429
    upstream.headers = {"Retry-After": "3600"}
    assert await b3.generate(db, _provider(upstream)) == 0
    assert len(upstream.calls) == 1
    assert await get_redis().ttl("brapi:blocked") > 3500
    upstream.calls.clear()
    assert await b3.generate(db, _provider(upstream)) == 0
    assert upstream.calls == []


async def test_crypto_keeps_its_strategy_and_signals(db: AsyncSession, upstream: Upstream) -> None:
    core = await signals.active_strategy(db)
    assert core.key == signals.DEFAULT_KEY
    await b3.generate(db, _provider(upstream))
    assert (await signals.active_strategy(db)).key == signals.DEFAULT_KEY
    assert await db.scalar(select(func.count()).select_from(AnalysisSignal)) == 2
    # The crypto ranking does not see the B3 rows.
    crypto = await signals.list_latest(db, "1d", classification=None, only_ids=None, limit=50)
    assert crypto == []


def _fundamentals(nav: str = "100") -> FiiFundamentals:
    return FiiFundamentals(Decimal(nav), Decimal("0.09"), date(2026, 9, 1), "tijolo")


def test_valuation_rewards_discount_without_chasing_extremes() -> None:
    today = NOW.date()
    score = lambda price: b3.score_valuation(Decimal(price), _fundamentals(), today)  # noqa: E731
    assert score("100")[0].score == Decimal(50)
    assert score("110")[0].score == Decimal(30)
    assert score("85")[0].score == Decimal(80)
    deep = score("50")
    assert deep[0].score == Decimal(85)
    assert any("Desconto" in r for r in deep[1])
    assert b3.score_valuation(Decimal(90), None, today)[2] is not None


def test_income_discounts_irregular_payments_and_distrusts_huge_yields() -> None:
    today = NOW.date()

    def payments(months: int, rate: str) -> list[FiiPayment]:
        return [
            FiiPayment(date(2026, 10, 15) - timedelta(days=30 * i), Decimal(rate))
            for i in range(months)
        ]

    regular = b3.score_income(Decimal(100), _fundamentals(), payments(12, "1"), today)
    assert regular[0].score == Decimal(80)
    assert regular[1] == []
    irregular = b3.score_income(Decimal(100), _fundamentals(), payments(6, "2"), today)
    assert irregular[0].score == Decimal(50)
    assert any("irregulares" in r for r in irregular[1])
    huge = b3.score_income(Decimal(100), _fundamentals(), payments(12, "2"), today)
    assert huge[0].score == Decimal(60)
    assert any("não recorrente" in r for r in huge[1])
    # Announced but unpaid income is not yield yet.
    future = [FiiPayment(date(2027, 1, 15), Decimal(50))]
    assert b3.score_income(Decimal(100), _fundamentals(), future, today)[3] == Decimal(9)
    assert b3.score_income(Decimal(100), None, [], today)[2] is not None


async def test_api_requires_auth_and_an_enabled_market(
    client: httpx.AsyncClient, outbox: Outbox
) -> None:
    assert (await client.get(f"{BASE}/signals")).status_code == 401
    await register_verified(client, outbox)
    await login(client)
    response = await client.get(f"{BASE}/signals")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "market_disabled"


async def test_api_returns_ranked_signals_and_the_asset_signal(
    client: httpx.AsyncClient, outbox: Outbox, db: AsyncSession, upstream: Upstream
) -> None:
    await b3.generate(db, _provider(upstream))
    await register_verified(client, outbox)
    await login(client)
    body = (await client.get(f"{BASE}/signals", params={"asset_type": "FII"})).json()
    assert [s["asset"]["symbol"] for s in body["items"]] == ["HGLG11"]
    assert "recomendação de investimento" in body["disclaimer"]
    assert "backtest" in body["disclaimer"]
    assert body["status"]["delay_seconds"] == 1800
    assert body["strategy"]["weights_pct"]["income"] == "30.0"

    asset = (await client.get(f"{BASE}/assets/PETR4/signal")).json()
    assert asset["asset_type"] == "STOCK"
    # BOVA11 is the benchmark, an ETF: it gets no signal of its own.
    etf = await client.get(f"{BASE}/assets/BOVA11/signal")
    assert etf.status_code == 404
    assert etf.json()["error"]["code"] == "signal_unavailable"
