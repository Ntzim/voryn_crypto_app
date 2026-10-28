"""Return methodologies against known reference values."""

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D

import pytest

from app.modules.portfolio.engine import ExternalFlow, LedgerEntry, TxType
from app.modules.portfolio.performance import (
    DailyPoint,
    change_24h,
    daily_series,
    twr_index,
    xirr,
)

BTC = uuid.uuid4()


def at(day: date, hour: int = 12) -> datetime:
    return datetime(day.year, day.month, day.day, hour, tzinfo=UTC)


def test_xirr_matches_excel_reference() -> None:
    # Microsoft's XIRR documentation example: 0.373362535 (37.34%).
    flows = [
        (datetime(2008, 1, 1, tzinfo=UTC), D(-10000)),
        (datetime(2008, 3, 1, tzinfo=UTC), D(2750)),
        (datetime(2008, 10, 30, tzinfo=UTC), D(4250)),
        (datetime(2009, 2, 15, tzinfo=UTC), D(3250)),
        (datetime(2009, 4, 1, tzinfo=UTC), D(2750)),
    ]
    result = xirr(flows)
    assert result is not None
    assert abs(result - D("0.373362535")) < D("0.000001")


def test_xirr_needs_both_signs() -> None:
    assert xirr([(datetime(2026, 1, 1, tzinfo=UTC), D(-100))]) is None
    assert (
        xirr(
            [(datetime(2026, 1, 1, tzinfo=UTC), D(-100)), (datetime(2026, 2, 1, tzinfo=UTC), D(-5))]
        )
        is None
    )


def test_twr_neutralizes_contribution_timing() -> None:
    # Day 1: invest 100 → 110 (+10%). Day 2: add 100 at start → 231 (+10% on 210).
    points = [
        DailyPoint(date(2026, 1, 1), D(110), D(100), D(100), False),
        DailyPoint(date(2026, 1, 2), D(231), D(100), D(200), False),
    ]
    index = twr_index(points)
    assert index[0] == D("1.1")
    assert index[1] == D("1.21")  # 21%, even though money grew 15.5% on 200 invested


def test_twr_with_unknown_opening_value_starts_flat() -> None:
    points = [
        DailyPoint(date(2026, 1, 1), D(500), D(0), D(0), False),
        DailyPoint(date(2026, 1, 2), D(550), D(0), D(0), False),
    ]
    assert twr_index(points, opening_value=None) == [D(1), D("1.1")]


def test_daily_series_values_holdings_with_fx_and_carries_prices() -> None:
    d1, d2, d3 = date(2026, 3, 1), date(2026, 3, 2), date(2026, 3, 3)
    entries = [
        LedgerEntry("a", TxType.BUY, at(d1), BTC, D("2"), gross=D("100")),  # BRL
    ]
    closes = {BTC: {d1: D("10"), d3: D("12")}}  # USD; d2 missing → carried
    fx = {d1: D("5"), d2: D("5"), d3: D("5.5")}
    points, ledger = daily_series(entries, d1, d3, closes, fx.get)
    assert [p.value for p in points] == [D("100"), D("100"), D("132")]
    assert [p.flow for p in points] == [D("100"), D(0), D(0)]
    assert not any(p.estimated for p in points)
    assert ledger.quantities() == {BTC: D("2")}


def test_daily_series_falls_back_to_transaction_price_when_no_close() -> None:
    d1 = date(2026, 3, 1)
    entries = [LedgerEntry("a", TxType.BUY, at(d1), BTC, D("2"), gross=D("100"))]
    points, _ = daily_series(entries, d1, d1, {}, lambda _: D(1))
    assert points[0].value == D("100")
    assert points[0].estimated is True


def test_change_24h_separates_market_effect_from_contributions() -> None:
    since = datetime(2026, 1, 1, tzinfo=UTC)
    flows = [
        ExternalFlow(since - timedelta(hours=1), D(999), "old"),  # outside the window
        ExternalFlow(since + timedelta(hours=3), D(500), "new"),
    ]
    result = change_24h(D(1000), D(1600), flows, since)
    assert result.net_flows == D(500)
    assert result.market_effect == D(100)
    assert result.pct == pytest.approx(D(100) / D(1500) * 100)
