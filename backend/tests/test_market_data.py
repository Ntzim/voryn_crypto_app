from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.market_data import service
from app.modules.market_data.models import Cryptocurrency, MarketPrice, MarketTicker
from app.modules.market_data.providers import coingecko
from app.modules.market_data.providers.base import FxQuote, MarketQuote, ProviderError
from app.modules.market_data.providers.coingecko import CoinGeckoProvider
from tests.conftest import API, Outbox, login, register_verified

NOW = datetime.now(UTC).replace(microsecond=0)


def _row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "bitcoin",
        "symbol": "btc",
        "name": "Bitcoin",
        "image": "https://assets.coingecko.com/coins/images/1/large/bitcoin.png",
        "market_cap_rank": 1,
        "current_price": 65000.12,
        "market_cap": 1280000000000,
        "total_volume": 31000000000,
        "high_24h": 66000,
        "low_24h": 64000,
        "price_change_percentage_1h_in_currency": 0.1,
        "price_change_percentage_24h_in_currency": 2.5,
        "price_change_percentage_7d_in_currency": -1.25,
        "circulating_supply": 19700000,
        "total_supply": 21000000,
        "max_supply": 21000000,
        "ath": 73738,
        "ath_change_percentage": -11.85,
        "ath_date": "2024-03-14T07:10:36.635Z",
        "last_updated": NOW.isoformat().replace("+00:00", "Z"),
    }
    row.update(overrides)
    return row


def _provider(handler: Any) -> CoinGeckoProvider:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.test/api/v3"
    )
    return CoinGeckoProvider(client=client)


# --------------------------------------------------------------------------- provider


async def test_provider_parses_decimals_exactly_and_drops_invalid_rows() -> None:
    import json

    body = json.dumps(
        [
            _row(),
            _row(id="tiny", symbol="tny", name="Tiny", current_price=1, market_cap_rank=2),
            _row(id="broken", current_price=-5),
            _row(id="no-price", current_price=None),
            _row(id="future", last_updated=(NOW + timedelta(hours=2)).isoformat()),
        ]
    ).replace('"current_price": 1,', '"current_price": 0.000012345678901234,')

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/coins/markets"
        assert request.url.params["vs_currency"] == "usd"
        return httpx.Response(200, text=body)

    quotes = await _provider(handler).fetch_top_markets("USD", 100)
    assert [q.source_id for q in quotes] == ["bitcoin", "tiny"]
    assert quotes[0].symbol == "BTC"
    assert quotes[0].price == Decimal("65000.12")
    assert quotes[1].price == Decimal("0.000012345678901234")


async def test_provider_retries_rate_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(coingecko.asyncio, "sleep", fake_sleep)  # type: ignore[attr-defined]
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "7"})
        return httpx.Response(200, json=[_row()])

    quotes = await _provider(handler).fetch_top_markets("USD", 10)
    assert len(quotes) == 1 and calls["n"] == 2 and sleeps == [7.0]


async def test_provider_does_not_retry_client_errors() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(401, json={"error": "invalid key"})

    with pytest.raises(ProviderError):
        await _provider(handler).fetch_top_markets("USD", 10)
    assert calls["n"] == 1


async def test_provider_derives_usd_brl_from_btc_rates() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"rates": {"usd": {"value": 65000.0}, "brl": {"value": 357500.0}}}
        )

    fx = await _provider(handler).fetch_fx_rate("USD", "BRL")
    assert fx.rate == Decimal("5.5")


# --------------------------------------------------------------------------- service


def _quote(
    source_id: str, symbol: str, rank: int, price: str, change: str, cap: str
) -> MarketQuote:
    return MarketQuote(
        source_id=source_id,
        symbol=symbol,
        name=source_id.title(),
        image_url=None,
        market_cap_rank=rank,
        quote_currency="USD",
        price=Decimal(price),
        market_cap=Decimal(cap),
        fully_diluted_valuation=None,
        total_volume=Decimal("1000"),
        high_24h=None,
        low_24h=None,
        change_pct_1h=None,
        change_pct_24h=Decimal(change),
        change_pct_7d=None,
        circulating_supply=None,
        total_supply=None,
        max_supply=None,
        ath=Decimal(price) * 2,
        ath_change_pct=Decimal("-50"),
        ath_date=None,
        source_updated_at=NOW,
    )


class FakeProvider:
    name = "coingecko"

    def __init__(self, quotes: list[MarketQuote], rate: str = "5.25") -> None:
        self.quotes = quotes
        self.rate = Decimal(rate)

    async def fetch_top_markets(self, vs_currency: str, limit: int) -> list[MarketQuote]:
        return self.quotes[:limit]

    async def fetch_fx_rate(self, base: str, quote: str) -> FxQuote:
        return FxQuote(base, quote, self.rate, NOW)


QUOTES = [
    _quote("bitcoin", "BTC", 1, "65000.10", "2.5", "600"),
    _quote("ethereum", "ETH", 2, "3200.55", "-1.2", "300"),
    _quote("solana", "SOL", 3, "150.00", "7.8", "100"),
]


async def test_sync_upserts_and_dedupes_history(db: AsyncSession) -> None:
    provider = FakeProvider(QUOTES)
    assert await service.sync_markets(db, provider) == 3
    # Same provider timestamp twice: ticker refreshed, history not duplicated.
    await service.sync_markets(db, provider)
    assert await db.scalar(select(func.count()).select_from(Cryptocurrency)) == 3
    assert await db.scalar(select(func.count()).select_from(MarketTicker)) == 3
    assert await db.scalar(select(func.count()).select_from(MarketPrice)) == 3

    later = [replace(q, source_updated_at=NOW + timedelta(minutes=5)) for q in QUOTES[:2]]
    await service.sync_markets(db, FakeProvider(later))
    assert await db.scalar(select(func.count()).select_from(MarketPrice)) == 5
    # Solana dropped out of the tracked universe: hidden from listings, history kept.
    listing = await service.list_assets(
        db, currency="USD", q=None, sort="rank", order="asc", page=1, page_size=50
    )
    assert [a.slug for a in listing.items] == ["bitcoin", "ethereum"]


async def test_brl_conversion_is_exact_and_documented(db: AsyncSession) -> None:
    provider = FakeProvider(QUOTES, rate="5.25")
    await service.sync_markets(db, provider)
    with pytest.raises(service.FxUnavailableError):
        await service.list_assets(
            db, currency="BRL", q=None, sort="rank", order="asc", page=1, page_size=50
        )
    await service.sync_fx(db, provider)
    detail = await service.get_asset(db, "bitcoin", "BRL")
    assert detail.asset.price == Decimal("65000.10") * Decimal("5.25")
    assert detail.asset.change_pct_24h == Decimal("2.5")  # percentages are not converted
    assert detail.status.fx_rate == Decimal("5.25")
    assert detail.status.change_basis == "USD"


async def test_listing_search_sort_and_pagination(db: AsyncSession) -> None:
    await service.sync_markets(db, FakeProvider(QUOTES))
    by_change = await service.list_assets(
        db, currency="USD", q=None, sort="change_24h", order="desc", page=1, page_size=2
    )
    assert by_change.total == 3
    assert [a.symbol for a in by_change.items] == ["SOL", "BTC"]

    search = await service.list_assets(
        db, currency="USD", q="eth", sort="rank", order="asc", page=1, page_size=50
    )
    assert [a.symbol for a in search.items] == ["ETH"]
    # LIKE wildcards in user input are literals.
    wildcard = await service.list_assets(
        db, currency="USD", q="%", sort="rank", order="asc", page=1, page_size=50
    )
    assert wildcard.total == 0


async def test_staleness_flag(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    await service.sync_markets(db, FakeProvider(QUOTES))
    fresh = await service.list_assets(
        db, currency="USD", q=None, sort="rank", order="asc", page=1, page_size=1
    )
    assert fresh.status.is_stale is False
    monkeypatch.setattr(service, "utcnow", lambda: datetime.now(UTC) + timedelta(hours=1))
    stale = await service.list_assets(
        db, currency="USD", q=None, sort="rank", order="asc", page=1, page_size=1
    )
    assert stale.status.is_stale is True


async def test_overview_aggregates(db: AsyncSession) -> None:
    await service.sync_markets(db, FakeProvider(QUOTES))
    data = await service.overview(db, "USD", movers=1)
    assert data.tracked_assets == 3
    assert data.total_market_cap == Decimal("1000")
    assert data.btc_dominance_pct == Decimal("60")
    assert data.advancers_24h == 2 and data.decliners_24h == 1
    assert data.top_gainers[0].symbol == "SOL"
    assert data.top_losers[0].symbol == "ETH"


# --------------------------------------------------------------------------- API


async def test_market_api_requires_auth_and_serializes_decimals_as_strings(
    client: httpx.AsyncClient,
    outbox: Outbox,
    db: AsyncSession,
) -> None:
    assert (await client.get(f"{API}/market/assets")).status_code == 401
    await service.sync_markets(db, FakeProvider(QUOTES))
    await register_verified(client, outbox)
    await login(client)

    response = await client.get(f"{API}/market/assets", params={"sort": "price", "order": "desc"})
    assert response.status_code == 200
    body = response.json()
    assert body["items"][0]["price"] == "65000.100000000000000000"
    assert body["status"]["attribution"] == service.ATTRIBUTION

    assert (await client.get(f"{API}/market/assets/bitcoin")).status_code == 200
    assert (await client.get(f"{API}/market/assets/unknown-coin")).status_code == 404
    assert (await client.get(f"{API}/market/assets/DROP TABLE")).status_code == 422
    assert (await client.get(f"{API}/market/overview")).status_code == 200
