"""Multimarket isolation: exchange instruments share the catalogue table with crypto, so
every crypto feature must keep ignoring them until its market is explicitly supported."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.redis import get_redis
from app.modules.market_data import calendars, exchanges, service
from app.modules.market_data.models import Cryptocurrency, MarketTicker
from app.modules.market_data.providers import brapi
from app.modules.market_data.providers.base import ProviderError
from app.modules.market_data.providers.brapi import BrapiProvider
from app.modules.signals import service as signals
from tests.conftest import API, Outbox, login, register_verified
from tests.fakes import FakeProvider, quote

QUOTES = [
    quote("bitcoin", "BTC", 1, "65000.10", "2.5", "600"),
    quote("ethereum", "ETH", 2, "3200.55", "-1.2", "300"),
]


async def _b3_etf(db: AsyncSession, *, quote_currency: str = "USD") -> Cryptocurrency:
    # A Bitcoin ETF listed on B3: name and rank are chosen to collide with crypto lookups.
    # The ticker is stored in USD on purpose, the worst case for the currency filters.
    now = datetime.now(UTC)
    etf = Cryptocurrency(
        source="brapi",
        source_id="QBTC11",
        symbol="QBTC11",
        name="QR Bitcoin ETF",
        market_cap_rank=1,
        market="B3",
        asset_type="ETF",
        exchange="BVMF",
        currency="BRL",
    )
    db.add(etf)
    await db.flush()
    db.add(
        MarketTicker(
            cryptocurrency_id=etf.id,
            quote_currency=quote_currency,
            price=Decimal("10"),
            market_cap=Decimal("999999"),
            change_pct_24h=Decimal("50"),
            source="brapi",
            source_updated_at=now,
            fetched_at=now,
            delay_seconds=1800,
        )
    )
    await db.commit()
    return etf


async def test_existing_crypto_rows_default_to_crypto_market(db: AsyncSession) -> None:
    await service.sync_markets(db, FakeProvider(QUOTES))
    btc = await service.resolve_asset(db, "BTC")
    assert btc is not None
    assert (btc.market, btc.asset_type, btc.currency, btc.exchange) == (
        "CRYPTO",
        "CRYPTO",
        "USD",
        None,
    )
    ticker = (await service.live_tickers(db, [btc.id]))[btc.id]
    assert ticker.delay_seconds == 0


async def test_exchange_instruments_stay_out_of_crypto_features(db: AsyncSession) -> None:
    await service.sync_markets(db, FakeProvider(QUOTES))
    etf = await _b3_etf(db)

    listing = await service.list_assets(
        db, currency="USD", q=None, sort="rank", order="asc", page=1, page_size=50
    )
    assert [a.symbol for a in listing.items] == ["BTC", "ETH"]
    watch = await service.list_assets(
        db,
        currency="USD",
        q=None,
        sort="rank",
        order="asc",
        page=1,
        page_size=50,
        only_ids=[etf.id],
    )
    assert watch.total == 0

    overview = await service.overview(db, "USD")
    assert overview.tracked_assets == 2
    assert overview.top_gainers[0].symbol == "BTC"

    assert [c.symbol for c in await service.search_assets(db, "bitcoin")] == ["BTC"]
    assert await service.resolve_asset(db, "QBTC11") is None
    assert await service.cryptos_by_id(db, [etf.id]) == {}
    assert await service.get_crypto(db, etf.id) is None
    with pytest.raises(service.NotFoundError):
        await service.get_asset(db, "QBTC11", "USD")

    assert etf.id not in await signals.universe(db)


async def test_symbol_is_unique_within_an_exchange_market(db: AsyncSession) -> None:
    await _b3_etf(db, quote_currency="BRL")
    db.add(
        Cryptocurrency(
            source="other",
            source_id="qbtc11",
            symbol="QBTC11",
            name="Duplicate",
            market="B3",
            asset_type="ETF",
            currency="BRL",
        )
    )
    with pytest.raises(IntegrityError):
        await db.commit()


# --------------------------------------------------------------------------- settings


def test_markets_flag_parses_csv_and_always_keeps_crypto(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MARKETS_ENABLED", "B3, B3")
    assert Settings().markets_enabled == ["CRYPTO", "B3"]
    monkeypatch.delenv("MARKETS_ENABLED")
    default = Settings()
    assert default.markets_enabled == ["CRYPTO"]
    assert not default.market_enabled("B3")


@pytest.fixture
def b3_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "markets_enabled", ["CRYPTO", "B3"])


# --------------------------------------------------------------------------- calendars

SP = ZoneInfo("America/Sao_Paulo")
NY = ZoneInfo("America/New_York")


def test_b3_session_states() -> None:
    wednesday = datetime(2026, 10, 28, 14, 0, tzinfo=SP)
    assert calendars.status("B3", wednesday).state == "open"
    assert calendars.status("B3", wednesday).last_close == datetime(2026, 10, 27, 17, tzinfo=SP)

    early = calendars.status("B3", datetime(2026, 10, 28, 9, 0, tzinfo=SP))
    assert early.state == "closed" and early.next_open == datetime(2026, 10, 28, 10, tzinfo=SP)

    # Sunday before Finados (Monday 2026-11-02, a B3 holiday).
    sunday = calendars.status("B3", datetime(2026, 11, 1, 12, 0, tzinfo=SP))
    assert sunday.state == "closed"
    assert sunday.last_close == datetime(2026, 10, 30, 17, tzinfo=SP)
    assert sunday.next_open == datetime(2026, 11, 3, 10, tzinfo=SP)

    assert calendars.status("CRYPTO", wednesday).state == "always_open"


def test_us_session_follows_new_york_time_and_holidays() -> None:
    # 2026-11-26 is Thanksgiving; the 27th trades (early close not modelled).
    thanksgiving = calendars.status("US", datetime(2026, 11, 26, 12, 0, tzinfo=NY))
    assert thanksgiving.state == "closed"
    assert thanksgiving.next_open == datetime(2026, 11, 27, 9, 30, tzinfo=NY)
    # 14:45 UTC is 09:45 in New York after the DST change on 2026-11-01.
    assert calendars.status("US", datetime(2026, 11, 2, 14, 45, tzinfo=UTC)).state == "open"


def test_weekend_quote_taken_after_the_close_is_not_stale() -> None:
    sunday = datetime(2026, 11, 1, 12, 0, tzinfo=SP)
    friday_close = datetime(2026, 10, 30, 17, 0, tzinfo=SP)
    hour = timedelta(hours=1)
    assert not calendars.is_stale("B3", friday_close, sunday, hour)
    assert calendars.is_stale("B3", friday_close - hour, sunday, hour)


def test_reference_time_is_delayed_and_capped_at_the_close() -> None:
    during = datetime(2026, 10, 28, 14, 0, tzinfo=SP)
    assert exchanges.reference_time("B3", during, 1800) == during - timedelta(minutes=30)
    saturday = datetime(2026, 10, 31, 12, 0, tzinfo=SP)
    assert exchanges.reference_time("B3", saturday, 1800) == datetime(2026, 10, 30, 17, tzinfo=SP)


# --------------------------------------------------------------------------- brapi


def _ticker(symbol: str, sub_type: str | None = "stock", **overrides: Any) -> dict[str, Any]:
    # Shape of a real /api/v2/tickers row (checked against brapi on 2026-10-31).
    row: dict[str, Any] = {
        "symbol": symbol,
        "name": symbol,
        "longName": f"{symbol} SA",
        "assetType": "stock",
        "subType": sub_type,
        "exchange": "B3",
        "currency": "BRL",
        "sector": "Finance",
        "subsector": "Bancos",
        "isActive": True,
        "logoUrl": f"https://icons.brapi.dev/icons/{symbol}.svg",
        "quote": {"lastPrice": 13.43, "changePercent": -5.42, "volume": 91210400, "marketCap": 1},
    }
    row.update(overrides)
    return row


def _page(rows: list[dict[str, Any]], page: int, has_next: bool) -> dict[str, Any]:
    return {
        "results": rows,
        "indexes": [{"symbol": "^BVSP"}],
        "pagination": {"page": page, "limit": 1000, "totalPages": 2, "hasNextPage": has_next},
    }


PAGES = {
    1: _page(
        [
            _ticker(
                "B3SA3",
                name="B3 S.A. - BRASIL. BOLSA. BALCÃƒO",
                quote={"lastPrice": 13.43, "changePercent": -5.42, "volume": 91210400},
            ),
            _ticker("BOVA11", "etf", name="BOVA11", longName="iShares Ibovespa"),
            _ticker("HGLG11", "fii"),
            _ticker("AAPL34", "bdr"),
            _ticker("XPTO11", "fidc"),
            _ticker("OLD3", isActive=False),
            _ticker("ZERO3", quote={"lastPrice": 0}),
            _ticker("bad symbol!"),
        ],
        1,
        True,
    ),
    2: _page([_ticker("PETR4", quote={"lastPrice": 38.12, "changePercent": 1.5})], 2, False),
}


def _brapi(handler: Any) -> BrapiProvider:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://brapi.test/api"
    )
    return BrapiProvider(client=client)


def _catalogue_handler(request: httpx.Request) -> httpx.Response:
    assert request.url.path == "/api/v2/tickers"
    return httpx.Response(200, json=PAGES[int(request.url.params["page"])])


async def test_brapi_catalogue_maps_types_and_drops_invalid_rows() -> None:
    provider = _brapi(_catalogue_handler)
    quotes = {q.symbol: q for q in await provider.fetch_catalogue()}
    assert provider.requests == 2
    assert set(quotes) == {"B3SA3", "BOVA11", "HGLG11", "AAPL34", "PETR4"}
    assert quotes["B3SA3"].name == "B3 S.A. - BRASIL. BOLSA. BALCÃO"
    assert quotes["B3SA3"].market_cap is None
    assert quotes["BOVA11"].name == "iShares Ibovespa"  # name equal to the symbol
    assert [quotes[s].asset_type for s in ("BOVA11", "HGLG11", "AAPL34", "PETR4")] == [
        "ETF",
        "FII",
        "BDR",
        "STOCK",
    ]
    assert quotes["PETR4"].price == Decimal("38.12")


async def test_brapi_sends_token_only_in_the_authorization_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "brapi_token", SecretStr("tok-123"))
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _catalogue_handler(request)

    provider = BrapiProvider()
    headers = provider._client.headers
    await provider.aclose()
    provider._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://brapi.test/api", headers=headers
    )
    await provider.fetch_catalogue()
    assert seen[0].headers["authorization"] == "Bearer tok-123"
    assert "tok-123" not in str(seen[0].url)


async def test_brapi_retries_rate_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(brapi.asyncio, "sleep", fake_sleep)  # type: ignore[attr-defined]
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "7"})
        return _catalogue_handler(request)

    assert len(await _brapi(handler).fetch_catalogue()) == 5
    assert sleeps == [7.0]

    def unauthorized(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401)

    with pytest.raises(ProviderError):
        await _brapi(unauthorized).fetch_catalogue()


async def test_brapi_daily_history_is_sorted_and_validated() -> None:
    def bar(stamp: int, o: float, h: float, low: float, c: float) -> dict[str, Any]:
        return {"date": stamp, "open": o, "high": h, "low": low, "close": c, "volume": 100}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["symbols"] == "PETR4"
        # brapi returns newest first; the last row has high < low and must be dropped.
        bars = [
            bar(1761919200, 30, 31, 29, 30.5),
            bar(1761832800, 29, 30, 28, 29.5),
            bar(1761746400, 29, 28, 30, 29),
        ]
        return httpx.Response(200, json={"results": [{"data": {"historicalDataPrice": bars}}]})

    bars = await _brapi(handler).fetch_daily_history("PETR4")
    assert [b.close for b in bars] == [Decimal("29.5"), Decimal("30.5")]
    with pytest.raises(ValueError):
        await _brapi(handler).fetch_daily_history("../etc")


# --------------------------------------------------------------------------- sync + API


async def test_b3_sync_is_refused_while_the_market_is_disabled(db: AsyncSession) -> None:
    with pytest.raises(exchanges.MarketDisabledError):
        await exchanges.sync_b3(db, _brapi(_catalogue_handler))


async def test_b3_sync_stores_delayed_brl_quotes(
    db: AsyncSession, b3_enabled: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    await service.sync_markets(db, FakeProvider(QUOTES))
    wednesday = datetime(2026, 10, 28, 14, 0, tzinfo=SP)
    monkeypatch.setattr(exchanges, "utcnow", lambda: wednesday)

    assert await exchanges.sync_b3(db, _brapi(_catalogue_handler)) == 5
    petr = (await exchanges.search(db, "PETR4", ["B3"]))[0]
    instrument = petr.instrument
    assert (instrument.market, instrument.exchange, instrument.currency) == ("B3", "BVMF", "BRL")
    assert petr.ticker is not None
    assert petr.ticker.quote_currency == "BRL"
    assert petr.ticker.price == Decimal("38.12")
    assert petr.ticker.delay_seconds == 1800
    assert petr.ticker.source_updated_at == wednesday - timedelta(minutes=30)
    assert await get_redis().get("brapi:usage:2026-10") == "2"

    # Crypto is untouched by the B3 rows.
    listing = await service.list_assets(
        db, currency="USD", q=None, sort="rank", order="asc", page=1, page_size=50
    )
    assert [a.symbol for a in listing.items] == ["BTC", "ETH"]

    # An instrument that leaves the catalogue is deactivated, not deleted.
    def without_petr(request: httpx.Request) -> httpx.Response:
        if request.url.params["page"] == "2":
            return httpx.Response(200, json=_page([], 2, False))
        return _catalogue_handler(request)

    assert await exchanges.sync_b3(db, _brapi(without_petr)) == 4
    assert await exchanges.search(db, "PETR4", ["B3"]) == []


async def test_market_endpoints_only_expose_enabled_markets(
    client: httpx.AsyncClient,
    outbox: Outbox,
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert (await client.get(f"{API}/market/markets")).status_code == 401
    await service.sync_markets(db, FakeProvider(QUOTES))
    await _b3_etf(db, quote_currency="BRL")
    await register_verified(client, outbox)
    await login(client)

    markets = (await client.get(f"{API}/market/markets")).json()
    assert [m["market"] for m in markets] == ["CRYPTO"]
    assert markets[0]["delay_seconds"] == 0

    search_url = f"{API}/market/instruments/search"
    search = (await client.get(search_url, params={"q": "bitcoin"})).json()
    assert [h["symbol"] for h in search] == ["BTC"]
    b3_only = await client.get(search_url, params={"q": "QBTC", "market": "B3"})
    assert b3_only.status_code == 200 and b3_only.json() == []

    monkeypatch.setattr(get_settings(), "markets_enabled", ["CRYPTO", "B3"])
    markets = (await client.get(f"{API}/market/markets")).json()
    b3 = next(m for m in markets if m["market"] == "B3")
    assert b3["currency"] == "BRL" and b3["delay_seconds"] == 1800
    assert "brapi" in b3["attribution"]
    hits = (await client.get(search_url, params={"q": "bitcoin"})).json()
    assert {(h["market"], h["symbol"]) for h in hits} == {("CRYPTO", "BTC"), ("B3", "QBTC11")}
    etf = next(h for h in hits if h["market"] == "B3")
    assert etf["currency"] == "BRL" and etf["delay_seconds"] == 1800
    assert Decimal(etf["price"]) == Decimal("10")
