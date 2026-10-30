"""The platform's own signal strategy (`voryn-core`) replayed candle by candle."""

from collections.abc import Sequence
from decimal import Decimal

from app.modules.backtesting.engine import Strategy
from app.modules.market_data.providers.base import Candle, Timeframe
from app.modules.signals import engine as signal_engine
from app.modules.technical_analysis.service import analyze

#: candles given to the analysis at each step (EMA 200 needs 200 to be defined)
WINDOW = 300


class VorynSignal(Strategy):
    """Enter on "potencial de compra", exit on "potencial de venda", hold otherwise.

    Each decision runs the same analysis and scoring as the live signals on the candles
    up to t. Historical market breadth is not stored, so the market component uses only
    Bitcoin's trend at the same candle.
    """

    key = "voryn_signal"
    warmup = 200

    def __init__(
        self,
        timeframe: Timeframe,
        weights: dict[str, Decimal],
        thresholds: dict[str, Decimal],
        version: int,
        btc_candles: Sequence[Candle] | None,
    ) -> None:
        self.timeframe, self.weights, self.thresholds = timeframe, weights, thresholds
        self.version = version
        self._btc = list(btc_candles) if btc_candles is not None else None
        self._btc_index: dict[object, int] = {}
        self._btc_trend: dict[int, str | None] = {}
        self._decisions: dict[int, str] = {}

    def prepare(self, candles: Sequence[Candle]) -> None:
        if self._btc is not None:
            self._btc_index = {c.open_time: i for i, c in enumerate(self._btc)}

    def _btc_trend_at(self, candle: Candle) -> str | None:
        if self._btc is None:
            return None
        j = self._btc_index.get(candle.open_time)
        if j is None:
            return None
        if j not in self._btc_trend:
            result = analyze(self._btc[max(0, j - WINDOW + 1) : j + 1], self.timeframe)
            self._btc_trend[j] = result.trend.classification if result.trend else None
        return self._btc_trend[j]

    def classification(self, candles: Sequence[Candle], t: int) -> str | None:
        if t in self._decisions:
            return self._decisions[t]
        window = candles[max(0, t - WINDOW + 1) : t + 1]
        result = analyze(window, self.timeframe)
        if result.snapshot is None or result.trend is None:
            return None
        btc_trend = (
            result.trend.classification if self._btc is None else self._btc_trend_at(candles[t])
        )
        last = candles[t]
        signal = signal_engine.evaluate(
            snapshot=result.snapshot,
            trend=result.trend,
            supports=result.supports,
            resistances=result.resistances,
            bandwidth_percentile=result.bandwidth_percentile,
            last_candle_up=last.close >= last.open,
            market=signal_engine.MarketContext(None, btc_trend),
            stale=False,
            weights=self.weights,
            thresholds=self.thresholds,
        )
        self._decisions[t] = signal.classification
        return signal.classification

    def decide(self, candles: Sequence[Candle], t: int, in_position: bool) -> bool:
        c = self.classification(candles, t)
        if c == "buy_potential":
            return True
        if c == "sell_potential":
            return False
        return in_position

    def params(self) -> dict[str, int | str]:
        return {"strategy": "voryn-core", "version": self.version}
