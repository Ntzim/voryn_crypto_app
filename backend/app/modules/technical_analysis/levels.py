"""Support and resistance detection.

Methodology:
1. Swing points (fractals): a candle whose high (low) is the strict maximum (minimum) of the
   `k` candles on each side. Only closed candles are used.
2. Clustering: swing prices closer than `tolerance` (default 0.5 × ATR, at least 0.15% of
   price) are merged into one zone; its level is the mean of the merged prices.
3. Strength = number of swings in the zone ("touches"); recency = last touch.
4. Zones below the current price are supports, above are resistances; the nearest three of
   each are returned, preferring zones touched at least twice.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.modules.market_data.providers.base import Candle


@dataclass(frozen=True, slots=True)
class Level:
    price: Decimal
    touches: int
    last_touch: datetime
    kind: str  # "support" | "resistance"


def swing_points(candles: Sequence[Candle], k: int = 3) -> list[tuple[Decimal, datetime]]:
    points = []
    for i in range(k, len(candles) - k):
        window = candles[i - k : i + k + 1]
        c = candles[i]
        others = [w for j, w in enumerate(window) if j != k]
        if all(c.high > w.high for w in others):
            points.append((c.high, c.open_time))
        if all(c.low < w.low for w in others):
            points.append((c.low, c.open_time))
    return points


def detect_levels(
    candles: Sequence[Candle], atr_value: Decimal | None, k: int = 3, limit: int = 3
) -> tuple[list[Level], list[Level]]:
    if len(candles) < 2 * k + 1:
        return [], []
    price = candles[-1].close
    tolerance = max(
        atr_value * Decimal("0.5") if atr_value else Decimal(0), price * Decimal("0.0015")
    )

    zones: list[list[tuple[Decimal, datetime]]] = []
    for point in sorted(swing_points(candles, k), key=lambda p: p[0]):
        if zones and point[0] - _mean(zones[-1]) <= tolerance:
            zones[-1].append(point)
        else:
            zones.append([point])

    levels = [
        Level(
            price=_mean(z),
            touches=len(z),
            last_touch=max(t for _, t in z),
            kind="support" if _mean(z) < price else "resistance",
        )
        for z in zones
    ]

    def pick(kind: str) -> list[Level]:
        side = [lv for lv in levels if lv.kind == kind]
        side.sort(key=lambda lv: (lv.touches < 2, abs(lv.price - price)))
        return sorted(side[:limit], key=lambda lv: abs(lv.price - price))

    return pick("support"), pick("resistance")


def _mean(zone: Sequence[tuple[Decimal, datetime]]) -> Decimal:
    return sum((p for p, _ in zone), Decimal(0)) / len(zone)
