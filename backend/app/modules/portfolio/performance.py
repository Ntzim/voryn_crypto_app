"""Performance analytics: daily valuation series, TWR, XIRR and 24h attribution.

Pure functions over the engine's ledger plus price/FX inputs.

Methodology (documented for users in docs/PORTFOLIO.md):

- **Daily valuation** — holdings at the end of each UTC day × that day's close × that day's
  USD→reporting-currency rate. Missing closes are carried forward; if an asset has no close
  yet, its last transaction price is used and the point is flagged `estimated`.
- **TWR** (time-weighted return) — daily sub-period returns chained geometrically,
  r_d = V_d / (V_{d−1} + F_d) − 1, with flows assumed at the start of the day. TWR measures
  the investments' performance independent of when money was added or withdrawn.
- **XIRR** (money-weighted, annualized) — the rate that zeroes the NPV of all external
  flows plus today's value; it reflects the investor's timing decisions.
"""

import math
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, localcontext

from app.modules.portfolio.engine import ZERO, ExternalFlow, Ledger, LedgerEntry

ONE = Decimal(1)


@dataclass(frozen=True, slots=True)
class DailyPoint:
    day: date
    value: Decimal
    flow: Decimal
    net_invested: Decimal
    estimated: bool


def _day_end(day: date) -> datetime:
    return datetime.combine(day + timedelta(days=1), time(), UTC)


def daily_series(
    entries: Sequence[LedgerEntry],
    start: date,
    end: date,
    closes_usd: dict[uuid.UUID, dict[date, Decimal]],
    usd_to_reporting: Callable[[date], Decimal | None],
) -> tuple[list[DailyPoint], Ledger]:
    """Value the portfolio at each day close in [start, end].

    Entries before `start` are applied first and form the opening position.
    Returns the points and the ledger state after `end`.
    """
    ledger = Ledger()
    i = 0
    opening = datetime.combine(start, time(), UTC)
    cumulative = ZERO
    while i < len(entries) and entries[i].executed_at < opening:
        cumulative += ledger.apply(entries[i])
        i += 1

    last_close: dict[uuid.UUID, Decimal] = {}
    last_rate: Decimal | None = None
    points: list[DailyPoint] = []
    day = start
    with localcontext() as ctx:
        ctx.prec = 40
        while day <= end:
            flow = ZERO
            day_end = _day_end(day)
            while i < len(entries) and entries[i].executed_at < day_end:
                flow += ledger.apply(entries[i])
                i += 1
            cumulative += flow

            rate = usd_to_reporting(day)
            if rate is not None:
                last_rate = rate
            value, estimated = ZERO, False
            for asset, quantity in ledger.quantities().items():
                close = closes_usd.get(asset, {}).get(day)
                if close is not None:
                    last_close[asset] = close
                else:
                    close = last_close.get(asset)
                if close is not None and last_rate is not None:
                    value += quantity * close * last_rate
                else:
                    value += quantity * ledger.last_price.get(asset, ZERO)
                    estimated = True
            points.append(DailyPoint(day, value, flow, cumulative, estimated))
            day += timedelta(days=1)
    return points, ledger


def twr_index(
    points: Sequence[DailyPoint], *, opening_value: Decimal | None = ZERO
) -> list[Decimal]:
    """Cumulative growth index after each point (1.0 = no gain).

    `opening_value` is the value before the first point; pass None when unknown (series
    truncated by available history), which makes the first day's return zero.
    """
    index: list[Decimal] = []
    level = ONE
    previous = opening_value
    with localcontext() as ctx:
        ctx.prec = 40
        for point in points:
            if previous is not None:
                denominator = previous + point.flow
                if denominator > 0:
                    level *= point.value / denominator
            index.append(level)
            previous = point.value
    return index


def chain(level: Decimal, previous_value: Decimal, flow: Decimal, value: Decimal) -> Decimal:
    """Extend an index by one sub-period."""
    denominator = previous_value + flow
    if denominator <= 0:
        return level
    with localcontext() as ctx:
        ctx.prec = 40
        return level * value / denominator


def xirr(flows: Sequence[tuple[datetime, Decimal]]) -> Decimal | None:
    """Annualized money-weighted return (actual/365), investor's sign convention.

    `flows`: (when, amount) with deposits negative and withdrawals/terminal value positive.
    Newton–Raphson with a bisection fallback; None when no solution exists.
    """
    if len(flows) < 2 or not any(a < 0 for _, a in flows) or not any(a > 0 for _, a in flows):
        return None
    t0 = min(t for t, _ in flows)
    data = [((t - t0).total_seconds() / 86400 / 365.0, float(a)) for t, a in flows]

    def npv(rate: float) -> float:
        return math.fsum(a / (1.0 + rate) ** y for y, a in data)

    def d_npv(rate: float) -> float:
        return math.fsum(-y * a / (1.0 + rate) ** (y + 1) for y, a in data)

    rate = 0.1
    for _ in range(100):
        try:
            value, slope = npv(rate), d_npv(rate)
        except (OverflowError, ZeroDivisionError):
            break
        if abs(value) < 1e-9:
            return Decimal(repr(round(rate, 10)))
        if slope == 0:
            break
        candidate = rate - value / slope
        if candidate <= -0.9999 or candidate != candidate:  # NaN guard
            break
        rate = candidate

    low, high = -0.9999, 1000.0
    try:
        f_low, f_high = npv(low), npv(high)
    except OverflowError:
        return None
    if f_low * f_high > 0:
        return None
    for _ in range(300):
        mid = (low + high) / 2
        f_mid = npv(mid)
        if abs(f_mid) < 1e-9:
            break
        if f_low * f_mid < 0:
            high = mid
        else:
            low, f_low = mid, f_mid
    return Decimal(repr(round((low + high) / 2, 10)))


@dataclass(frozen=True, slots=True)
class Change24h:
    value_then: Decimal
    value_now: Decimal
    net_flows: Decimal
    market_effect: Decimal
    pct: Decimal | None


def change_24h(
    value_then: Decimal, value_now: Decimal, flows: Sequence[ExternalFlow], since: datetime
) -> Change24h:
    """Split the 24h value change into market effect and contributions/withdrawals."""
    net = sum((f.amount for f in flows if f.at > since), ZERO)
    effect = value_now - value_then - net
    base = value_then + max(net, ZERO)
    pct = effect / base * 100 if base > 0 else None
    return Change24h(value_then, value_now, net, effect, pct)
