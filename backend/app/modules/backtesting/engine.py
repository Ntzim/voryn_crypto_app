"""Event-driven backtester for long-only spot strategies.

Rules that keep results honest (docs/BACKTESTING.md):

* A decision for candle *t* sees only candles ``0..t`` (closed); it is executed at the
  **open of candle t+1** — never at the close that produced the signal.
* Every fill pays slippage (worse price) and a fee on the notional.
* All-in / all-out, no leverage, no shorting; idle capital earns nothing.
* Parameters may be optimized on the training segment only; the validation segment is
  run once, from flat, with the chosen parameters.
"""

import itertools
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from app.modules.market_data.providers.base import Candle, Timeframe
from app.modules.technical_analysis import indicators as ind

ZERO = Decimal(0)
BPS = Decimal(10000)
INITIAL_CAPITAL = Decimal(10000)
PERIODS_PER_YEAR: dict[str, int] = {"1d": 365, "4h": 6 * 365, "1h": 24 * 365}


@dataclass(frozen=True, slots=True)
class Costs:
    fee_bps: Decimal
    slippage_bps: Decimal


class Strategy(ABC):
    key: str
    #: candles needed before the first decision (indicator warm-up)
    warmup: int = 0

    def prepare(self, candles: Sequence[Candle]) -> None:  # noqa: B027 - optional hook
        """Precompute *causal* series (value at t depends only on candles ≤ t)."""

    @abstractmethod
    def decide(self, candles: Sequence[Candle], t: int, in_position: bool) -> bool:
        """Desired position after the close of candle t (True = fully invested)."""

    def params(self) -> dict[str, int | str]:
        return {}


class BuyAndHold(Strategy):
    key = "buy_and_hold"

    def decide(self, candles: Sequence[Candle], t: int, in_position: bool) -> bool:
        return True


class EmaCross(Strategy):
    key = "ema_cross"

    def __init__(self, fast: int = 12, slow: int = 50) -> None:
        if not 2 <= fast < slow <= 200:
            raise ValueError("EMA rápida deve ser menor que a lenta (2–200).")
        self.fast, self.slow, self.warmup = fast, slow, slow
        self._fast: ind.Series = []
        self._slow: ind.Series = []

    def prepare(self, candles: Sequence[Candle]) -> None:
        closes = [c.close for c in candles]
        self._fast, self._slow = ind.ema(closes, self.fast), ind.ema(closes, self.slow)

    def decide(self, candles: Sequence[Candle], t: int, in_position: bool) -> bool:
        f, s = self._fast[t], self._slow[t]
        return f is not None and s is not None and f > s

    def params(self) -> dict[str, int | str]:
        return {"fast": self.fast, "slow": self.slow}


class RsiReversion(Strategy):
    key = "rsi_reversion"

    def __init__(self, low: int = 30, high: int = 70, period: int = 14) -> None:
        if not 5 <= low < high <= 95:
            raise ValueError("Limiar de compra deve ser menor que o de venda (5–95).")
        self.low, self.high, self.period, self.warmup = low, high, period, period + 1
        self._rsi: ind.Series = []

    def prepare(self, candles: Sequence[Candle]) -> None:
        self._rsi = ind.rsi([c.close for c in candles], self.period)

    def decide(self, candles: Sequence[Candle], t: int, in_position: bool) -> bool:
        value = self._rsi[t]
        if value is None:
            return in_position
        if not in_position:
            return value < self.low
        return value <= self.high

    def params(self) -> dict[str, int | str]:
        return {"low": self.low, "high": self.high, "period": self.period}


class MacdCross(Strategy):
    key = "macd_cross"

    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9) -> None:
        if not 2 <= fast < slow <= 100 or not 2 <= signal <= 50:
            raise ValueError("A média rápida do MACD deve ser menor que a lenta.")
        self.fast, self.slow, self.signal = fast, slow, signal
        self.warmup = slow + signal
        self._hist: ind.Series = []

    def prepare(self, candles: Sequence[Candle]) -> None:
        self._hist = ind.macd([c.close for c in candles], self.fast, self.slow, self.signal)[2]

    def decide(self, candles: Sequence[Candle], t: int, in_position: bool) -> bool:
        value = self._hist[t]
        return value is not None and value > 0

    def params(self) -> dict[str, int | str]:
        return {"fast": self.fast, "slow": self.slow, "signal": self.signal}


# --------------------------------------------------------------------------- simulation


@dataclass(slots=True)
class Trade:
    entry_time: datetime
    entry_price: Decimal
    quantity: Decimal
    cost: Decimal  # cash spent, fees included
    exit_time: datetime | None = None
    exit_price: Decimal | None = None
    proceeds: Decimal | None = None  # cash received, fees deducted

    @property
    def return_pct(self) -> Decimal | None:
        if self.proceeds is None or self.cost <= 0:
            return None
        return (self.proceeds / self.cost - 1) * 100


@dataclass(slots=True)
class Run:
    equity: list[tuple[datetime, Decimal]] = field(default_factory=list)
    exposure: list[bool] = field(default_factory=list)
    trades: list[Trade] = field(default_factory=list)
    fees: Decimal = ZERO


def simulate(
    candles: Sequence[Candle],
    strategy: Strategy,
    start: int,
    end: int,
    costs: Costs,
    capital: Decimal = INITIAL_CAPITAL,
) -> Run:
    """Run over candles[start:end]; the strategy must already be prepared on `candles`."""
    fee, slip = costs.fee_bps / BPS, costs.slippage_bps / BPS
    cash, qty = capital, ZERO
    run = Run()
    for t in range(start, end):
        close = candles[t].close
        run.equity.append((candles[t].open_time, cash + qty * close))
        run.exposure.append(qty > 0)
        if t + 1 >= end:
            break  # the next open is outside the segment: nothing more can be executed
        want = strategy.decide(candles, t, qty > 0)
        fill_open = candles[t + 1].open
        if want and qty == 0:
            price = fill_open * (1 + slip)
            qty = cash / (price * (1 + fee))
            paid = qty * price * fee
            run.fees += paid
            run.trades.append(Trade(candles[t + 1].open_time, price, qty, cash))
            cash = ZERO
        elif not want and qty > 0:
            price = fill_open * (1 - slip)
            gross = qty * price
            paid = gross * fee
            run.fees += paid
            cash = gross - paid
            trade = run.trades[-1]
            trade.exit_time, trade.exit_price, trade.proceeds = (
                candles[t + 1].open_time,
                price,
                cash,
            )
            qty = ZERO
    return run


# --------------------------------------------------------------------------- metrics


@dataclass(frozen=True, slots=True)
class Metrics:
    start: datetime | None
    end: datetime | None
    bars: int
    final_equity: Decimal
    total_return_pct: Decimal
    cagr_pct: Decimal | None
    max_drawdown_pct: Decimal
    volatility_pct: Decimal | None
    sharpe: Decimal | None
    trades: int
    win_rate_pct: Decimal | None
    avg_trade_pct: Decimal | None
    #: gross profit ÷ gross loss of closed trades
    profit_factor: Decimal | None
    exposure_pct: Decimal
    fees: Decimal


def metrics(run: Run, timeframe: Timeframe, capital: Decimal = INITIAL_CAPITAL) -> Metrics:
    values = [v for _, v in run.equity]
    final = values[-1] if values else capital
    total = (final / capital - 1) * 100
    start = run.equity[0][0] if run.equity else None
    end = run.equity[-1][0] if run.equity else None
    cagr = None
    if start and end and (end - start).days >= 30 and final > 0:
        years = Decimal((end - start).total_seconds()) / Decimal(365 * 86400)
        cagr = ((final / capital) ** (1 / years) - 1) * 100
    peak, worst = ZERO, ZERO
    for v in values:
        peak = max(peak, v)
        if peak > 0:
            worst = min(worst, v / peak - 1)
    returns = [b / a - 1 for a, b in itertools.pairwise(values) if a > 0]
    vol = sharpe = None
    if len(returns) >= 30:
        mean = sum(returns, ZERO) / len(returns)
        var = sum(((r - mean) ** 2 for r in returns), ZERO) / (len(returns) - 1)
        sd = var.sqrt()
        periods = Decimal(PERIODS_PER_YEAR.get(timeframe, 365))
        vol = sd * periods.sqrt() * 100
        sharpe = mean / sd * periods.sqrt() if sd > 0 else None
    closed = [t.return_pct for t in run.trades if t.return_pct is not None]
    pnl = [t.proceeds - t.cost for t in run.trades if t.proceeds is not None]
    gains = sum((x for x in pnl if x > 0), ZERO)
    losses = -sum((x for x in pnl if x < 0), ZERO)
    wins = [r for r in closed if r > 0]
    return Metrics(
        start=start,
        end=end,
        bars=len(values),
        final_equity=final,
        total_return_pct=total,
        cagr_pct=cagr,
        max_drawdown_pct=worst * 100,
        volatility_pct=vol,
        sharpe=sharpe,
        trades=len(run.trades),
        win_rate_pct=Decimal(len(wins)) / len(closed) * 100 if closed else None,
        avg_trade_pct=sum(closed, ZERO) / len(closed) if closed else None,
        profit_factor=gains / losses if losses > 0 else None,
        exposure_pct=Decimal(sum(run.exposure)) / len(run.exposure) * 100 if run.exposure else ZERO,
        fees=run.fees,
    )
