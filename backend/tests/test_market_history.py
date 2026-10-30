from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.market_data import service
from app.modules.market_data.models import Cryptocurrency, DailyPrice, MarketTicker
from app.modules.market_data.providers.base import DailyClose
from app.modules.market_data.providers.bcb import BcbPtaxProvider
from app.modules.market_data.providers.coingecko import CoinGeckoProvider
from tests.fakes import FakeFxHistory, FakeProvider, quote

TODAY = datetime.now(UTC).date()


async def test_held_assets_outside_top_n_get_tickers_but_stay_unlisted(db: AsyncSession) -> None:
    provider = FakeProvider(
        [quote("bitcoin", "BTC", 1, "100")], extra=[quote("tiny-coin", "TINY", 900, "0.01")]
    )
    await service.sync_markets(db, provider, extra_source_ids=["tiny-coin", "bitcoin"])
    tiny = (
        await db.execute(select(Cryptocurrency).where(Cryptocurrency.source_id == "tiny-coin"))
    ).scalar_one()
    assert tiny.is_active is False and tiny.market_cap_rank is None
    assert await db.scalar(select(func.count()).select_from(MarketTicker)) == 2


async def test_daily_backfill_skips_covered_assets(db: AsyncSession) -> None:
    await service.sync_markets(db, FakeProvider([quote("bitcoin", "BTC", 1, "100")]))
    btc = (await db.execute(select(Cryptocurrency.id))).scalar_one()
    closes = [DailyClose(TODAY - timedelta(days=n), D(100 + n)) for n in range(1, 6)]
    provider = FakeProvider([], closes={"bitcoin": closes})
    since = TODAY - timedelta(days=5)

    assert await service.backfill_daily_prices(db, provider, {btc: "bitcoin"}, since) == 5
    assert await service.backfill_daily_prices(db, provider, {btc: "bitcoin"}, since) == 0
    assert provider.history_calls == ["bitcoin"]
    assert await db.scalar(select(func.count()).select_from(DailyPrice)) == 5


async def test_fx_daily_carries_rates_over_weekends(db: AsyncSession) -> None:
    friday = date(2026, 3, 6)
    fx = FakeFxHistory({friday: D("5.10"), friday + timedelta(days=3): D("5.20")})
    await service.backfill_fx_history(db, fx, friday)
    rates = await service.usd_brl_daily(db, friday, friday + timedelta(days=3))
    assert [rates[friday + timedelta(days=n)] for n in range(4)] == [
        D("5.10"),
        D("5.10"),
        D("5.10"),
        D("5.20"),
    ]


async def test_bcb_ptax_parsing_and_sanity_band() -> None:
    payload = (
        '{"value": [{"cotacaoVenda": 5.0140, "dataHoraCotacao": "2026-10-20 13:09:36.250"},'
        '{"cotacaoVenda": 0.0001, "dataHoraCotacao": "2026-10-21 13:00:00.000"}]}'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert "CotacaoDolarPeriodo" in request.url.path
        assert request.url.params["@dataInicial"] == "'10-20-2026'"
        return httpx.Response(200, text=payload)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://bcb.test")
    quotes = await BcbPtaxProvider(client).fetch_usd_brl(date(2026, 10, 20), date(2026, 10, 21))
    assert len(quotes) == 1
    assert quotes[0].rate == D("5.0140")
    # 13:09 Brasília (UTC−3) = 16:09 UTC
    assert quotes[0].observed_at.astimezone(UTC).hour == 16


async def test_coingecko_daily_closes_shift_midnight_points_to_previous_day() -> None:
    def ms(d: date) -> int:
        return int(datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp() * 1000)

    d1, d2 = TODAY - timedelta(days=2), TODAY - timedelta(days=1)
    live = int(datetime.now(UTC).timestamp() * 1000)
    body = {"prices": [[ms(d1), 10.5], [ms(d2), 11.25], [ms(TODAY), 12.0], [live, 12.5]]}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://cg.test")
    closes = await CoinGeckoProvider(client=client).fetch_daily_closes("bitcoin", 3)
    # Point at D 00:00 UTC is the close of D−1; the live trailing point is dropped.
    assert [(c.day, c.close) for c in closes] == [
        (d1 - timedelta(days=1), D("10.5")),
        (d1, D("11.25")),
        (d2, D("12.0")),
    ]
