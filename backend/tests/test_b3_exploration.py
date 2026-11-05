"""B3 exploration API: delayed data labeled as such, nothing invented when brapi says no."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.redis import get_redis
from app.modules.market_data import exchanges, service
from app.modules.market_data.providers import brapi
from app.modules.market_data.providers.brapi import BrapiProvider
from tests.conftest import API, Outbox, login, register_verified
from tests.fakes import FakeProvider, quote

SP = ZoneInfo("America/Sao_Paulo")
WEDNESDAY = datetime(2026, 10, 28, 14, 0, tzinfo=SP)
BASE = f"{API}/market/exchanges/B3"


def _ticker(
    symbol: str, price: float, change: float, volume: int, sub_type: str = "stock"
) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "name": f"{symbol} SA",
        "subType": sub_type,
        "currency": "BRL",
        "sector": "Finance",
        "isActive": True,
        "logoUrl": f"https://icons.brapi.dev/icons/{symbol}.svg",
        "quote": {
            "lastPrice": price,
            "changePercent": change,
            "volume": volume,
            "marketCap": int(price * volume * 10),
        },
    }


CATALOGUE = [
    _ticker("PETR4", 50, 1.5, 60_000_000),
    _ticker("VALE3", 60, -2, 30_000_000),
    _ticker("BOVA11", 165, -0.5, 2_000_000, "etf"),
    _ticker("HGLG11", 150, 0.7, 100_000, "fii"),
    _ticker("AAPL34", 90, 3, 200_000, "bdr"),
    # Barely traded: a huge change here must not lead the movers.
    _ticker("TINY3", 2, 80, 100),
    _ticker("GONE3", 2, -60, 100),
    # Fractional lot of PETR4: never listed.
    _ticker("PETR4F", 50, 260, 3),
]

DETAIL = {
    "regularMarketOpen": 49.5,
    "regularMarketDayHigh": 51,
    "regularMarketDayLow": 49,
    "regularMarketPreviousClose": 49.26,
    "fiftyTwoWeekLow": 29.53,
    "fiftyTwoWeekHigh": 59.79,
}


def _bar(stamp: int, close: float) -> dict[str, Any]:
    return {
        "date": stamp,
        "open": close,
        "high": close + 1,
        "low": close - 1,
        "close": close,
        "volume": 10,
    }


class Upstream:
    """brapi stand-in: counts on-demand calls; `status` simulates a refused request."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.status = 200
        self.headers: dict[str, str] = {}
        self.code = "MISSING_TOKEN"

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/v2/tickers"):
            return httpx.Response(
                200, json={"results": CATALOGUE, "pagination": {"hasNextPage": False}}
            )
        self.calls.append(path)
        if self.status != 200:
            return httpx.Response(
                self.status, headers=self.headers, json={"error": True, "code": self.code}
            )
        if path.endswith("/v2/stocks/quote"):
            symbol = request.url.params["symbols"]
            row = {"requestedSymbol": symbol, "symbol": symbol, "data": DETAIL}
            return httpx.Response(200, json={"results": [row]})
        bars = [_bar(1761919200, 51), _bar(1761832800, 50)]
        return httpx.Response(200, json={"results": [{"data": {"historicalDataPrice": bars}}]})


@pytest.fixture
def upstream(monkeypatch: pytest.MonkeyPatch) -> Upstream:
    fake = Upstream()
    original = BrapiProvider

    def factory(*_: Any, **kwargs: Any) -> BrapiProvider:
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(fake), base_url="https://brapi.test/api"
        )
        return original(client=client, **kwargs)

    monkeypatch.setattr(brapi, "BrapiProvider", factory)
    return fake


@pytest.fixture
async def b3(
    db: AsyncSession, upstream: Upstream, monkeypatch: pytest.MonkeyPatch
) -> Callable[[datetime], None]:
    monkeypatch.setattr(get_settings(), "markets_enabled", ["CRYPTO", "B3"])
    # Independent of a real token in a developer's .env.
    monkeypatch.setattr(get_settings(), "brapi_token", None)
    monkeypatch.setattr(exchanges, "utcnow", lambda: WEDNESDAY)
    await service.sync_markets(db, FakeProvider([quote("bitcoin", "BTC", 1, "65000")]))
    provider = BrapiProvider(
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(upstream), base_url="https://brapi.test/api"
        )
    )
    assert await exchanges.sync_b3(db, provider) == 7

    def at(moment: datetime) -> None:
        monkeypatch.setattr(exchanges, "utcnow", lambda: moment)

    return at


@pytest.fixture
async def signed_in(client: httpx.AsyncClient, outbox: Outbox) -> httpx.AsyncClient:
    await register_verified(client, outbox)
    await login(client)
    return client


async def test_exploration_requires_auth_and_an_enabled_market(
    client: httpx.AsyncClient, outbox: Outbox
) -> None:
    assert (await client.get(f"{BASE}/overview")).status_code == 401
    await register_verified(client, outbox)
    await login(client)
    for path in ("/overview", "/assets", "/assets/PETR4", "/assets/PETR4/history"):
        response = await client.get(f"{BASE}{path}")
        assert response.status_code == 404, path
        assert response.json()["error"]["code"] == "market_disabled"
    assert (await client.get(f"{API}/market/exchanges/US/overview")).status_code == 422


async def test_overview_ignores_illiquid_movers_and_labels_the_delay(
    b3: Any, signed_in: httpx.AsyncClient
) -> None:
    data = (await signed_in.get(f"{BASE}/overview")).json()
    assert [a["symbol"] for a in data["top_gainers"]] == ["AAPL34", "PETR4", "HGLG11"]
    assert [a["symbol"] for a in data["top_losers"]] == ["VALE3", "BOVA11"]
    assert data["most_traded"][0]["symbol"] == "PETR4"
    assert (data["advancers"], data["decliners"]) == (3, 2)
    assert data["counts"] == {"STOCK": 4, "ETF": 1, "FII": 1, "BDR": 1}
    assert data["reference"]["symbol"] == "BOVA11"
    assert data["reference"]["asset_type"] == "ETF"

    status = data["status"]
    assert status["state"] == "open"
    assert status["delay_seconds"] == 1800
    assert status["is_stale"] is False
    assert "brapi" in status["attribution"]
    as_of = datetime.fromisoformat(status["as_of"])
    assert as_of == WEDNESDAY - timedelta(minutes=30)


async def test_listing_filters_sorts_paginates_and_excludes_crypto(
    b3: Any, signed_in: httpx.AsyncClient
) -> None:
    listing = (await signed_in.get(f"{BASE}/assets")).json()
    symbols = [a["symbol"] for a in listing["items"]]
    assert listing["total"] == 7
    assert symbols[0] == "PETR4"
    assert "BTC" not in symbols and "PETR4F" not in symbols
    petr = listing["items"][0]
    assert Decimal(petr["traded_value"]) == Decimal(50) * Decimal(60_000_000)
    assert petr["currency"] == "BRL"

    fii = (await signed_in.get(f"{BASE}/assets", params={"asset_type": "FII"})).json()
    assert [a["symbol"] for a in fii["items"]] == ["HGLG11"]
    search = (await signed_in.get(f"{BASE}/assets", params={"q": "vale"})).json()
    assert [a["symbol"] for a in search["items"]] == ["VALE3"]
    wildcard = (await signed_in.get(f"{BASE}/assets", params={"q": "%"})).json()
    assert wildcard["total"] == 0
    page = (
        await signed_in.get(
            f"{BASE}/assets", params={"sort": "price", "order": "asc", "page": 2, "page_size": 2}
        )
    ).json()
    assert [a["symbol"] for a in page["items"]] == ["PETR4", "VALE3"]


async def test_stale_data_is_flagged_but_a_closed_session_is_not_stale(
    b3: Any, signed_in: httpx.AsyncClient
) -> None:
    b3(WEDNESDAY + timedelta(hours=2, minutes=30))  # 16:30: session open, last sync at 14:00
    status = (await signed_in.get(f"{BASE}/overview")).json()["status"]
    assert status["is_stale"] is True

    b3(datetime(2026, 10, 27, 20, 0, tzinfo=SP))  # data newer than the last close
    status = (await signed_in.get(f"{BASE}/overview")).json()["status"]
    assert status["state"] == "closed"
    assert status["is_stale"] is False


async def test_detail_is_cached_and_reports_the_session_figures(
    b3: Any, signed_in: httpx.AsyncClient, upstream: Upstream
) -> None:
    for _ in range(3):
        data = (await signed_in.get(f"{BASE}/assets/PETR4")).json()
    assert len(upstream.calls) == 1
    assert data["detail_unavailable"] is None
    assert Decimal(data["week52_high"]) == Decimal("59.79")
    assert Decimal(data["previous_close"]) == Decimal("49.26")
    assert Decimal(data["asset"]["price"]) == Decimal(50)
    assert (await signed_in.get(f"{BASE}/assets/NOPE3")).status_code == 404
    assert (await signed_in.get(f"{BASE}/assets/petr4")).status_code == 422


async def test_without_a_token_nothing_is_invented_and_requests_stop(
    b3: Any, signed_in: httpx.AsyncClient, upstream: Upstream
) -> None:
    upstream.status = 401
    for _ in range(3):
        detail = (await signed_in.get(f"{BASE}/assets/VALE3")).json()
        history = (await signed_in.get(f"{BASE}/assets/VALE3/history")).json()
    # One request per endpoint, however many page views.
    assert len(upstream.calls) == 2
    assert detail["detail_unavailable"] == "token_required"
    assert detail["week52_high"] is None and detail["open"] is None
    # The catalogue quote is still real and shown.
    assert Decimal(detail["asset"]["price"]) == Decimal(60)
    assert history["unavailable"] == "token_required"
    assert history["bars"] == []


async def test_provider_outage_is_reported_and_retried_soon(
    b3: Any, signed_in: httpx.AsyncClient, upstream: Upstream
) -> None:
    upstream.status = 503
    history = (await signed_in.get(f"{BASE}/assets/PETR4/history")).json()
    assert history["unavailable"] == "provider_unavailable"
    ttl = await get_redis().ttl("b3:history:PETR4:3mo:a")
    assert 0 < ttl <= 60


async def test_history_is_ordered_and_limited_by_the_plan(
    b3: Any, signed_in: httpx.AsyncClient, upstream: Upstream
) -> None:
    data = (await signed_in.get(f"{BASE}/assets/PETR4/history")).json()
    assert data["allowed_ranges"] == ["1mo", "3mo"]
    assert data["unavailable"] is None
    assert [Decimal(b["close"]) for b in data["bars"]] == [Decimal(50), Decimal(51)]
    # Served from the cache with the same content.
    again = (await signed_in.get(f"{BASE}/assets/PETR4/history")).json()
    assert again["bars"] == data["bars"]
    assert len(upstream.calls) == 1

    refused = await signed_in.get(f"{BASE}/assets/PETR4/history", params={"range": "1y"})
    assert refused.status_code == 400
    assert refused.json()["error"]["code"] == "range_not_allowed"
    assert len(upstream.calls) == 1


async def test_free_quota_is_never_exceeded_by_page_views(
    b3: Any, signed_in: httpx.AsyncClient, upstream: Upstream
) -> None:
    await get_redis().set(f"brapi:usage:{WEDNESDAY:%Y-%m}", exchanges.BRAPI_MONTHLY_QUOTA)
    data = (await signed_in.get(f"{BASE}/assets/ITUB4")).status_code
    assert data == 404  # not in the catalogue: no upstream call either
    detail = (await signed_in.get(f"{BASE}/assets/PETR4")).json()
    assert detail["detail_unavailable"] == "quota_reached"
    assert upstream.calls == []


@pytest.mark.parametrize(
    ("status", "code", "reason"),
    [
        (401, "INVALID_TOKEN", "token_required"),
        (403, "FORBIDDEN", "plan_required"),
        (400, "INVALID_RANGE", "plan_required"),
        (404, "NOT_FOUND", "no_data"),
        (400, "BAD_REQUEST", "provider_unavailable"),
    ],
)
async def test_brapi_errors_become_an_honest_reason(
    b3: Any, signed_in: httpx.AsyncClient, upstream: Upstream, status: int, code: str, reason: str
) -> None:
    upstream.status, upstream.code = status, code
    history = (await signed_in.get(f"{BASE}/assets/PETR4/history")).json()
    assert history["unavailable"] == reason
    assert history["bars"] == []
    detail = (await signed_in.get(f"{BASE}/assets/PETR4")).json()
    assert detail["detail_unavailable"] == reason
    assert detail["open"] is None
    assert len(upstream.calls) == 2  # none of these is ever retried


async def test_retry_after_stops_every_call_until_it_passes(
    b3: Any, signed_in: httpx.AsyncClient, upstream: Upstream, db: AsyncSession
) -> None:
    upstream.status, upstream.code = 429, "RATE_LIMITED"
    upstream.headers = {"Retry-After": "3600"}
    assert (await signed_in.get(f"{BASE}/assets/PETR4")).json()["detail_unavailable"] == (
        "rate_limited"
    )
    assert 3500 < await get_redis().ttl("brapi:blocked") <= 3600
    # Other tickers, other endpoints and the sync all wait: the limit is per account.
    calls = len(upstream.calls)
    history = (await signed_in.get(f"{BASE}/assets/VALE3/history")).json()
    assert history["unavailable"] == "rate_limited"
    assert len(upstream.calls) == calls
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(upstream), base_url="https://brapi.test/api"
    )
    with pytest.raises(brapi.ProviderRateLimitError):
        await exchanges.sync_b3(db, BrapiProvider(client=client))

    await get_redis().delete("brapi:blocked")
    upstream.status = 200
    assert (await signed_in.get(f"{BASE}/assets/VALE3")).json()["detail_unavailable"] is None


def _provider(handler: Any) -> BrapiProvider:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://brapi.test/api"
    )
    return BrapiProvider(client=client)


async def test_session_details_use_symbols_within_the_plan_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested = request.url.params["symbols"].split(",")
        seen.append(request.url.params["symbols"])
        known = [s for s in requested if s != "NOPE3"]
        if not known:
            return httpx.Response(404, json={"error": True, "code": "NOT_FOUND"})
        rows = [
            {"requestedSymbol": s, "symbol": s, "data": {**DETAIL, "regularMarketOpen": None}}
            for s in known
        ]
        return httpx.Response(200, json={"results": rows})

    monkeypatch.setattr(get_settings(), "brapi_plan", "free")
    details = await _provider(handler).fetch_session_details(["PETR4", "NOPE3", "VALE3"])
    assert seen == ["PETR4", "NOPE3", "VALE3"]  # free plan: one asset per call
    assert set(details) == {"PETR4", "VALE3"}
    assert details["PETR4"].open is None  # null field stays null
    assert details["PETR4"].week52_high == Decimal("59.79")

    seen.clear()
    monkeypatch.setattr(get_settings(), "brapi_plan", "startup")
    details = await _provider(handler).fetch_session_details(["PETR4", "NOPE3", "VALE3"])
    assert seen == ["PETR4,NOPE3,VALE3"]
    assert set(details) == {"PETR4", "VALE3"}
    with pytest.raises(ValueError):
        await _provider(handler).fetch_session_details(["PETR4,../x"])


async def test_short_retry_after_is_waited_and_long_one_is_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(brapi.asyncio, "sleep", fake_sleep)  # type: ignore[attr-defined]
    answers = iter([httpx.Response(429, headers={"Retry-After": "7"})])

    def short(request: httpx.Request) -> httpx.Response:
        rows = [{"requestedSymbol": "PETR4", "data": DETAIL}]
        return next(answers, httpx.Response(200, json={"results": rows}))

    assert "PETR4" in await _provider(short).fetch_session_details(["PETR4"])
    assert sleeps == [7.0]

    sleeps.clear()

    def long(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "86400"})

    with pytest.raises(brapi.ProviderRateLimitError) as caught:
        await _provider(long).fetch_session_details(["PETR4"])
    assert caught.value.retry_after == 86400
    assert sleeps == []


async def test_history_keeps_a_bar_with_null_volume_and_drops_null_prices() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        rows = [
            {**_bar(1761919200, 51), "volume": None},
            {**_bar(1761832800, 50), "close": None},
        ]
        return httpx.Response(200, json={"results": [{"data": {"historicalDataPrice": rows}}]})

    bars = await _provider(handler).fetch_daily_history("PETR4")
    assert [(b.close, b.volume) for b in bars] == [(Decimal(51), None)]


def test_utc_quote_time_is_timezone_aware() -> None:
    # Guards the comparison in calendars.is_stale: naive datetimes would raise there.
    assert exchanges.utcnow().tzinfo is UTC
