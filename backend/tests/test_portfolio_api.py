"""Portfolio API: transactions, valuation in BRL/USD, history, CSV import, isolation."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal as D
from typing import Any

import httpx
import pytest
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.market_data import service as market
from app.modules.market_data.models import Cryptocurrency, DailyPrice
from app.modules.portfolio import router as portfolio_router
from tests.conftest import API, ClientFactory, Outbox, login, register_verified
from tests.fakes import FakeFxHistory, FakeProvider, quote

TODAY = datetime.now(UTC).date()
D3 = TODAY - timedelta(days=3)
D10 = TODAY - timedelta(days=10)
QUOTES = [
    quote("bitcoin", "BTC", 1, "100000", change="2"),
    quote("ethereum", "ETH", 2, "3000", change="-6"),
    quote("tether", "USDT", 3, "1"),
]
# Official USD→BRL at each past day: 4.00 (so the live 5.00 creates an FX effect).
PTAX = {TODAY - timedelta(days=n): D("4.0") for n in range(1, 40)}


@pytest.fixture
async def market_data(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    provider = FakeProvider(QUOTES, rate="5.0")
    await market.sync_markets(db, provider)
    await market.sync_fx(db, provider)
    fx = FakeFxHistory(PTAX)
    monkeypatch.setattr(portfolio_router, "BcbPtaxProvider", lambda: fx)
    rows = (await db.execute(select(Cryptocurrency.source_id, Cryptocurrency.id))).all()
    return {slug: str(id_) for slug, id_ in rows}


@pytest.fixture
async def user(
    client: httpx.AsyncClient, outbox: Outbox
) -> AsyncIterator[tuple[httpx.AsyncClient, str]]:
    await register_verified(client, outbox)
    await login(client)
    portfolios = (await client.get(f"{API}/portfolios")).json()
    assert len(portfolios) == 1 and portfolios[0]["name"] == "Minha carteira"
    yield client, portfolios[0]["id"]


def at(day: Any, hour: int = 15) -> str:
    return datetime.combine(day, time(hour), UTC).isoformat()


async def add(client: httpx.AsyncClient, pid: str, **fields: Any) -> httpx.Response:
    body = {"quote_currency": "BRL", **fields}
    return await client.post(f"{API}/portfolios/{pid}/transactions", json=body)


async def test_buy_is_valued_in_brl_and_usd_with_historical_fx(
    user: tuple[httpx.AsyncClient, str], market_data: dict[str, str]
) -> None:
    client, pid = user
    response = await add(
        client,
        pid,
        type="buy",
        asset_id=market_data["bitcoin"],
        quantity="0.5",
        unit_price="400000",
        fee_amount="100",
        executed_at=at(D3),
        exchange_id="mercado-bitcoin",
    )
    assert response.status_code == 201, response.text
    tx = response.json()
    assert tx["fx_usd_brl"].startswith("4.0")  # PTAX of the trade date, not today's rate
    assert D(tx["gross_amount"]) == D("200000")

    brl = (await client.get(f"{API}/portfolios/{pid}/summary", params={"currency": "BRL"})).json()
    # 0.5 BTC × 100,000 USD × 5.00 = 250,000 BRL; cost 200,100 BRL.
    assert D(brl["market_value"]) == D("250000")
    assert D(brl["cost_basis"]) == D("200100")
    assert D(brl["unrealized_pnl"]) == D("49900")
    assert D(brl["market_value_usd"]) == D("50000")
    position = brl["positions"][0]
    assert position["asset"]["symbol"] == "BTC"
    assert D(position["average_cost"]) == D("400200")
    assert D(position["weight_pct"]) == D("100")

    usd = (await client.get(f"{API}/portfolios/{pid}/summary", params={"currency": "USD"})).json()
    # In USD the same trade cost 200,100 / 4.00 = 50,025 → a small loss once FX is removed.
    assert D(usd["cost_basis"]) == D("50025")
    assert D(usd["unrealized_pnl"]) == D("-25")


async def test_sell_realizes_profit_and_reports_flows(
    user: tuple[httpx.AsyncClient, str], market_data: dict[str, str]
) -> None:
    client, pid = user
    eth = market_data["ethereum"]
    await add(
        client, pid, type="buy", asset_id=eth, quantity="2", unit_price="10000", executed_at=at(D10)
    )
    response = await add(
        client,
        pid,
        type="sell",
        asset_id=eth,
        quantity="1",
        unit_price="15000",
        fee_amount="50",
        executed_at=at(D3),
    )
    assert response.status_code == 201
    data = (await client.get(f"{API}/portfolios/{pid}/summary")).json()
    assert D(data["realized_pnl"]) == D("4950")  # 14,950 − 10,000
    assert D(data["total_inflows"]) == D("20000")
    assert D(data["total_outflows"]) == D("14950")
    assert D(data["net_invested"]) == D("5050")
    assert data["transaction_count"] == 2


async def test_cannot_sell_more_than_held_or_break_history_by_deleting(
    user: tuple[httpx.AsyncClient, str], market_data: dict[str, str]
) -> None:
    client, pid = user
    btc = market_data["bitcoin"]
    response = await add(
        client, pid, type="sell", asset_id=btc, quantity="1", unit_price="1", executed_at=at(D3)
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "insufficient_balance"
    assert "BTC" in response.json()["error"]["message"]

    buy = (
        await add(
            client, pid, type="buy", asset_id=btc, quantity="1", unit_price="1", executed_at=at(D10)
        )
    ).json()
    assert (
        await add(
            client, pid, type="sell", asset_id=btc, quantity="1", unit_price="2", executed_at=at(D3)
        )
    ).status_code == 201
    response = await client.delete(f"{API}/portfolios/{pid}/transactions/{buy['id']}")
    assert response.status_code == 422  # the later sale depends on this purchase
    # Moving the purchase after the sale is equally rejected.
    response = await client.put(
        f"{API}/portfolios/{pid}/transactions/{buy['id']}",
        json={
            "type": "buy",
            "asset_id": btc,
            "quantity": "1",
            "unit_price": "1",
            "quote_currency": "BRL",
            "executed_at": at(TODAY - timedelta(days=1)),
        },
    )
    assert response.status_code == 422
    listing = (await client.get(f"{API}/portfolios/{pid}/transactions")).json()
    assert listing["total"] == 2


async def test_transfer_and_conversion_are_internal(
    user: tuple[httpx.AsyncClient, str], market_data: dict[str, str]
) -> None:
    client, pid = user
    usdt, eth = market_data["tether"], market_data["ethereum"]
    await add(
        client,
        pid,
        type="buy",
        asset_id=usdt,
        quantity="1000",
        unit_price="1",
        quote_currency="USD",
        executed_at=at(D10),
        exchange_id="binance",
    )
    response = await add(
        client,
        pid,
        type="conversion",
        asset_id=usdt,
        quantity="600",
        unit_price="1",
        quote_currency="USD",
        to_asset_id=eth,
        to_quantity="0.2",
        executed_at=at(D3),
    )
    assert response.status_code == 201, response.text
    response = await add(
        client,
        pid,
        type="transfer",
        asset_id=eth,
        quantity="0.2",
        fee_quantity="0.001",
        executed_at=at(D3, 18),
        exchange_id="binance",
        to_exchange_id="carteira",
    )
    assert response.status_code == 201, response.text
    data = (await client.get(f"{API}/portfolios/{pid}/summary", params={"currency": "USD"})).json()
    assert D(data["total_inflows"]) == D("1000")  # only the original purchase
    assert D(data["total_outflows"]) == 0
    held = {p["asset"]["symbol"]: D(p["quantity"]) for p in data["positions"]}
    assert held == {"USDT": D("400"), "ETH": D("0.199")}


async def test_validation_rules(
    user: tuple[httpx.AsyncClient, str], market_data: dict[str, str]
) -> None:
    client, pid = user
    btc = market_data["bitcoin"]
    cases = [
        {"type": "buy", "asset_id": btc, "quantity": "1", "executed_at": at(D3)},  # no price
        {
            "type": "buy",
            "asset_id": btc,
            "quantity": "-1",
            "unit_price": "1",
            "executed_at": at(D3),
        },
        {
            "type": "buy",
            "asset_id": btc,
            "quantity": "1",
            "unit_price": "1",
            "executed_at": (datetime.now(UTC) + timedelta(days=2)).isoformat(),
        },
        {
            "type": "transfer",
            "asset_id": btc,
            "quantity": "1",
            "unit_price": "5",
            "executed_at": at(D3),
        },
        {
            "type": "buy",
            "asset_id": btc,
            "quantity": "1",
            "unit_price": "1",
            "executed_at": at(D3),
            "exchange_id": "nope",
        },
    ]
    for body in cases:
        response = await add(client, pid, **body)
        assert response.status_code == 422, body


async def test_portfolios_are_isolated(
    user: tuple[httpx.AsyncClient, str],
    market_data: dict[str, str],
    client_factory: ClientFactory,
    outbox: Outbox,
) -> None:
    client, pid = user
    await add(
        client,
        pid,
        type="buy",
        asset_id=market_data["bitcoin"],
        quantity="1",
        unit_price="1",
        executed_at=at(D3),
    )
    other = await client_factory()
    await register_verified(other, outbox, email="eve@example.com", name="Eve")
    await login(other, email="eve@example.com")
    for path in ("summary", "transactions", "performance"):
        assert (await other.get(f"{API}/portfolios/{pid}/{path}")).status_code == 404
    body = {
        "type": "buy",
        "asset_id": market_data["bitcoin"],
        "quantity": "1",
        "unit_price": "1",
        "quote_currency": "BRL",
        "executed_at": at(D3),
    }
    assert (await other.post(f"{API}/portfolios/{pid}/transactions", json=body)).status_code == 404


async def test_performance_twr_and_benchmarks(
    user: tuple[httpx.AsyncClient, str], market_data: dict[str, str], db: AsyncSession
) -> None:
    client, pid = user
    btc = market_data["bitcoin"]
    # Bitcoin closes rise 1% per day over the last 10 days.
    closes = []
    price = D("90000")
    for n in range(10, 0, -1):
        closes.append(
            {
                "cryptocurrency_id": btc,
                "day": TODAY - timedelta(days=n),
                "close": price,
                "source": "test",
            }
        )
        price *= D("1.01")
    await db.execute(insert(DailyPrice), closes)
    await db.commit()

    await add(
        client,
        pid,
        type="buy",
        asset_id=btc,
        quantity="1",
        unit_price="90000",
        quote_currency="USD",
        executed_at=at(D10, 1),
    )
    data = (
        await client.get(f"{API}/portfolios/{pid}/performance", params={"currency": "USD"})
    ).json()
    assert len(data["series"]) == 10
    first, last = data["series"][0], data["series"][-1]
    assert D(first["value"]) == D("90000")
    assert D(first["twr_pct"]) == 0
    # Fully invested in BTC: portfolio TWR tracks the BTC benchmark exactly.
    assert D(last["twr_pct"]) == D(last["btc_pct"])
    assert D(data["returns"]["d7"]) > 0
    assert data["returns"]["d30"] is None  # portfolio younger than 30 days
    assert data["xirr_applicable"] is False and data["xirr_pct"] is None
    assert data["history_complete"] is True


async def test_change_24h_separates_new_money(
    user: tuple[httpx.AsyncClient, str], market_data: dict[str, str]
) -> None:
    client, pid = user
    # Bought one hour ago at exactly today's price: all of the change is new money.
    await add(
        client,
        pid,
        type="buy",
        asset_id=market_data["bitcoin"],
        quantity="1",
        unit_price="100000",
        quote_currency="USD",
        executed_at=(datetime.now(UTC) - timedelta(hours=1)).isoformat(),
    )
    change = (
        await client.get(f"{API}/portfolios/{pid}/summary", params={"currency": "USD"})
    ).json()["change_24h"]
    assert D(change["net_flows"]) == D("100000")
    assert D(change["market_effect"]) == 0


async def test_insights_flag_concentration(
    user: tuple[httpx.AsyncClient, str], market_data: dict[str, str]
) -> None:
    client, pid = user
    await add(
        client,
        pid,
        type="buy",
        asset_id=market_data["bitcoin"],
        quantity="1",
        unit_price="100",
        executed_at=at(D3),
    )
    await add(
        client,
        pid,
        type="buy",
        asset_id=market_data["ethereum"],
        quantity="1",
        unit_price="100",
        executed_at=at(D3),
    )
    items = (await client.get(f"{API}/portfolios/{pid}/insights")).json()["items"]
    by_id = {i["id"]: i for i in items}
    assert by_id["concentration"]["severity"] == "risk"  # BTC ≈ 97%
    assert "Bitcoin representa" in by_id["concentration"]["message"]
    assert "mover_24h" in by_id  # ETH −6% in 24h
    assert all(i["basis"] for i in items)


CSV = """data;tipo;ativo;quantidade;preco_unitario;moeda;taxa;exchange;observacoes
{d10} 10:00;compra;BTC;0,5;350.000,00;BRL;10,00;mercado-bitcoin;primeira
{d3} 09:30;venda;bitcoin;0,1;400000;BRL;;mercado-bitcoin;
{d3} 09:30;compra;DOGE;1;1;BRL;;;
{d3} 09:31;voar;BTC;1;1;BRL;;;
"""


async def test_csv_preview_commit_and_dedupe(
    user: tuple[httpx.AsyncClient, str], market_data: dict[str, str]
) -> None:
    client, pid = user
    content = CSV.format(d10=D10.strftime("%d/%m/%Y"), d3=D3.isoformat())
    preview = (
        await client.post(f"{API}/portfolios/{pid}/imports/preview", json={"content": content})
    ).json()
    assert [r["status"] for r in preview["rows"]] == ["valid", "valid", "error", "error"]
    assert "ativo não encontrado" in preview["rows"][2]["errors"][0]
    assert "tipo desconhecido" in preview["rows"][3]["errors"][0]

    rejected = await client.post(
        f"{API}/portfolios/{pid}/imports/commit", json={"content": content}
    )
    assert rejected.status_code == 422
    committed = await client.post(
        f"{API}/portfolios/{pid}/imports/commit", json={"content": content, "skip_invalid": True}
    )
    assert committed.json() == {"imported": 2, "skipped": 2}

    again = (
        await client.post(f"{API}/portfolios/{pid}/imports/preview", json={"content": content})
    ).json()
    assert again["duplicates"] == 2
    recommit = await client.post(
        f"{API}/portfolios/{pid}/imports/commit", json={"content": content, "skip_invalid": True}
    )
    assert recommit.json()["imported"] == 0
    summary = (await client.get(f"{API}/portfolios/{pid}/summary")).json()
    assert D(summary["positions"][0]["quantity"]) == D("0.4")


async def test_csv_template_parses_cleanly(
    user: tuple[httpx.AsyncClient, str], market_data: dict[str, str]
) -> None:
    client, pid = user
    template = (await client.get(f"{API}/portfolios/csv-template")).text
    preview = (
        await client.post(f"{API}/portfolios/{pid}/imports/preview", json={"content": template})
    ).json()
    assert preview["errors"] == 0, preview


async def test_asset_search(
    user: tuple[httpx.AsyncClient, str], market_data: dict[str, str]
) -> None:
    client, _ = user
    results = (await client.get(f"{API}/market/search", params={"q": "eth"})).json()
    assert results[0]["symbol"] == "ETH"
    exchanges = (await client.get(f"{API}/exchanges")).json()
    assert {"id": "binance", "name": "Binance", "kind": "exchange"} in exchanges
