"""Multimarket isolation: exchange instruments share the catalogue table with crypto, so
every crypto feature must keep ignoring them until its market is explicitly supported."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.market_data import service
from app.modules.market_data.models import Cryptocurrency, MarketTicker
from app.modules.signals import service as signals
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
