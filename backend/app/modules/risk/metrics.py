"""Deterministic risk statistics over daily closes.

Pure functions, Decimal throughout. Conventions (documented in docs/RISK.md):
returns are simple daily returns of UTC daily closes; crypto trades every day, so
annualization uses 365 periods; standard deviation is the sample one (n − 1); historical
VaR is the empirical lower-tail quantile without interpolation.
"""

import itertools
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

ZERO = Decimal(0)
PERIODS_PER_YEAR = 365
MIN_OBSERVATIONS = 30


def simple_returns(closes: Sequence[Decimal]) -> list[Decimal]:
    return [b / a - 1 for a, b in itertools.pairwise(closes) if a > 0]


def mean(xs: Sequence[Decimal]) -> Decimal:
    return sum(xs, ZERO) / len(xs)


def covariance(xs: Sequence[Decimal], ys: Sequence[Decimal]) -> Decimal | None:
    n = min(len(xs), len(ys))
    if n < 2:
        return None
    mx, my = mean(xs[:n]), mean(ys[:n])
    return sum(((x - mx) * (y - my) for x, y in zip(xs[:n], ys[:n], strict=True)), ZERO) / (n - 1)


def stdev(xs: Sequence[Decimal]) -> Decimal | None:
    var = covariance(xs, xs)
    return var.sqrt() if var is not None else None


def annualized_volatility_pct(returns: Sequence[Decimal]) -> Decimal | None:
    if len(returns) < MIN_OBSERVATIONS:
        return None
    sd = stdev(returns)
    return sd * Decimal(PERIODS_PER_YEAR).sqrt() * 100 if sd is not None else None


def correlation(xs: Sequence[Decimal], ys: Sequence[Decimal]) -> Decimal | None:
    if min(len(xs), len(ys)) < MIN_OBSERVATIONS:
        return None
    cov, sx, sy = covariance(xs, ys), stdev(xs), stdev(ys)
    if cov is None or not sx or not sy:
        return None
    return cov / (sx * sy)


def beta(asset: Sequence[Decimal], market: Sequence[Decimal]) -> Decimal | None:
    if min(len(asset), len(market)) < MIN_OBSERVATIONS:
        return None
    cov, var = covariance(asset, market), covariance(market, market)
    if cov is None or not var:
        return None
    return cov / var


def historical_var(returns: Sequence[Decimal], confidence: Decimal) -> Decimal | None:
    """One-day loss (positive fraction) not exceeded with `confidence`, empirical quantile."""
    if len(returns) < MIN_OBSERVATIONS:
        return None
    ordered = sorted(returns)
    k = max(math.ceil((1 - confidence) * len(ordered)) - 1, 0)
    return max(-ordered[k], ZERO)


def expected_shortfall(returns: Sequence[Decimal], confidence: Decimal) -> Decimal | None:
    """Average loss on the days at or beyond the VaR threshold."""
    var = historical_var(returns, confidence)
    if var is None:
        return None
    tail = [r for r in returns if r <= -var]
    return max(-mean(tail), ZERO) if tail else var


@dataclass(frozen=True, slots=True)
class Drawdown:
    pct: Decimal  # ≤ 0
    peak: date | None
    trough: date | None
    current_pct: Decimal  # ≤ 0, from the running peak to the last value


def max_drawdown(values: Sequence[tuple[date, Decimal]]) -> Drawdown:
    peak_value, peak_day = ZERO, None
    worst, worst_peak, worst_trough = ZERO, None, None
    current = ZERO
    for day, value in values:
        if value > peak_value:
            peak_value, peak_day = value, day
        current = value / peak_value - 1 if peak_value > 0 else ZERO
        if current < worst:
            worst, worst_peak, worst_trough = current, peak_day, day
    return Drawdown(worst * 100, worst_peak, worst_trough, current * 100)


@dataclass(frozen=True, slots=True)
class Window:
    pct: Decimal
    start: date
    end: date


def worst_window(values: Sequence[tuple[date, Decimal]], days: int) -> Window | None:
    """Worst change between two values `days` apart (a historical stress scenario)."""
    worst: Window | None = None
    for (d0, v0), (d1, v1) in zip(values, values[days:], strict=False):
        if v0 <= 0:
            continue
        change = (v1 / v0 - 1) * 100
        if worst is None or change < worst.pct:
            worst = Window(change, d0, d1)
    return worst


def aligned(
    closes: Mapping[str, Mapping[date, Decimal]],
) -> tuple[list[date], dict[str, list[Decimal]]]:
    """Days present in every series (ascending) and each series' closes on those days."""
    if not closes:
        return [], {}
    days = sorted(set.intersection(*(set(c) for c in closes.values())))
    return days, {key: [series[d] for d in days] for key, series in closes.items()}


def hhi(weights: Sequence[Decimal]) -> Decimal:
    """Herfindahl–Hirschman index of weight fractions (1 = a single asset)."""
    return sum((w * w for w in weights), ZERO)
