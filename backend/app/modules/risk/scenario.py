"""Scenario simulator: what happens to today's holdings under a given market move.

A Bitcoin move propagates to each asset through its historical beta to Bitcoin;
stablecoins stay flat; per-asset overrides replace the propagated move. The result is a
mechanical what-if, not a forecast.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

ZERO = Decimal(0)
MIN_CHANGE = Decimal(-100)

Method = Literal["override", "stablecoin", "beta", "assumed_beta_1"]


@dataclass(frozen=True, slots=True)
class Exposure:
    key: str
    value: Decimal
    beta_btc: Decimal | None
    is_btc: bool
    is_stablecoin: bool


@dataclass(frozen=True, slots=True)
class Line:
    key: str
    value: Decimal
    change_pct: Decimal
    method: Method
    new_value: Decimal

    @property
    def pnl(self) -> Decimal:
        return self.new_value - self.value


def simulate(
    exposures: list[Exposure], btc_change_pct: Decimal, overrides: dict[str, Decimal]
) -> list[Line]:
    lines: list[Line] = []
    for e in exposures:
        method: Method
        if e.key in overrides:
            change, method = overrides[e.key], "override"
        elif e.is_stablecoin:
            change, method = ZERO, "stablecoin"
        elif e.is_btc:
            change, method = btc_change_pct, "beta"
        elif e.beta_btc is not None:
            change, method = e.beta_btc * btc_change_pct, "beta"
        else:
            change, method = btc_change_pct, "assumed_beta_1"
        change = max(change, MIN_CHANGE)  # a price cannot fall below zero
        lines.append(Line(e.key, e.value, change, method, e.value * (1 + change / 100)))
    return lines
