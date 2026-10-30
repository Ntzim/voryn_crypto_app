"""Data-quality gate for signals.

A signal is only as good as the candles behind it. Before the engine classifies, the
inputs are graded; anything other than "valid" makes the engine withhold buy/sell
("attention") and the reasons travel with the stored signal, so every recommendation
states the quality of the data it came from.

| Status       | Meaning                                                           |
|--------------|-------------------------------------------------------------------|
| valid        | complete, consistent and recent                                   |
| stale        | candles past their freshness window (provider down, sync failing) |
| incomplete   | too little history, or core indicators could not be computed      |
| anomalous    | prices disagree across sources, impossible moves, zero volume     |
| unavailable  | no fresh data at all; only an older (historical) signal exists    |

"unavailable" is assigned when reading (see service.for_asset); generation can only
produce the first four, because it needs candles to run.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal

from app.modules.market_data.providers.base import Candle, Timeframe
from app.modules.technical_analysis.schemas import Snapshot
from app.modules.technical_analysis.trend import MIN_CANDLES

DataQuality = Literal["valid", "stale", "incomplete", "anomalous", "unavailable"]
#: worst first; the reported status is the worst one found
SEVERITY: tuple[DataQuality, ...] = ("unavailable", "stale", "anomalous", "incomplete", "valid")

#: indicators every component of the score depends on
CORE_INDICATORS = ("rsi", "macd_hist", "ema50", "atr", "bb_bandwidth_pct", "volume_ratio")
#: how far the last close may sit from an independent fresh quote (CoinGecko). Daily
#: candles closed up to a day ago, so they get more room than intraday ones.
MAX_CROSS_SOURCE_DEVIATION: dict[str, Decimal] = {
    "15m": Decimal("0.10"),
    "1h": Decimal("0.10"),
    "4h": Decimal("0.15"),
    "1d": Decimal("0.25"),
    "1w": Decimal("0.40"),
}
#: a single candle moving more than this is treated as a data error, not a market move
MAX_SINGLE_CANDLE_MOVE = Decimal("0.5")


@dataclass(slots=True)
class QualityReport:
    status: DataQuality = "valid"
    reasons: list[str] = field(default_factory=list)

    def flag(self, status: DataQuality, reason: str) -> None:
        if SEVERITY.index(status) < SEVERITY.index(self.status):
            self.status = status
        self.reasons.append(reason)

    @property
    def ok(self) -> bool:
        return self.status == "valid"


def assess(
    *,
    closed: Sequence[Candle],
    snapshot: Snapshot,
    timeframe: Timeframe,
    is_stale: bool,
    quote_price: Decimal | None,
    quote_fetched_at: datetime | None,
    now: datetime,
    quote_max_age: timedelta,
) -> QualityReport:
    report = QualityReport()
    if is_stale:
        report.flag("stale", "Dados de preço desatualizados: a fonte não respondeu a tempo.")

    if len(closed) < MIN_CANDLES:
        report.flag(
            "incomplete",
            f"Histórico insuficiente: {len(closed)} candles fechados (mínimo {MIN_CANDLES}).",
        )
    missing = [name for name in CORE_INDICATORS if getattr(snapshot, name) is None]
    if missing:
        report.flag("incomplete", "Indicadores sem dados suficientes: " + ", ".join(missing) + ".")

    last = closed[-1]
    if last.volume == 0:
        report.flag("anomalous", "Volume zero no último candle fechado.")
    if len(closed) >= 2 and closed[-2].close > 0:
        move = abs(last.close / closed[-2].close - 1)
        if move > MAX_SINGLE_CANDLE_MOVE:
            report.flag(
                "anomalous", f"Variação de {move * 100:.0f}% em um único candle: possível erro."
            )
    quote_is_fresh = quote_fetched_at is not None and now - quote_fetched_at <= quote_max_age
    if quote_price is not None and quote_price > 0 and quote_is_fresh:
        deviation = abs(last.close - quote_price) / quote_price
        if deviation > MAX_CROSS_SOURCE_DEVIATION[timeframe]:
            report.flag(
                "anomalous",
                f"Preço diverge {deviation * 100:.0f}% da cotação de referência (CoinGecko).",
            )
    return report
