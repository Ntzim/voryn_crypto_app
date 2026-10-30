"""Deterministic technical indicators (no generative AI, no I/O).

Every function takes a full series and returns a list of the same length, with `None`
during the warm-up period, so outputs align 1:1 with the input candles.

Conventions (documented in docs/TECHNICAL_ANALYSIS.md):
- SMA: arithmetic mean of the last n values.
- EMA: α = 2/(n+1), seeded with the SMA of the first n values (TA-Lib convention).
- RSI: Wilder's method — first averages are simple means of the first n changes, then
  Wilder smoothing avg = (prev × (n−1) + current) / n.
- MACD: EMA(12) − EMA(26); signal = EMA(9) of MACD; histogram = MACD − signal.
- Bollinger: SMA(20) ± 2 × population standard deviation.
- ATR: Wilder smoothing of the true range, seeded with the SMA of the first n ranges.
"""

from collections.abc import Sequence
from decimal import Decimal, localcontext

Series = list[Decimal | None]
_PRECISION = 34


def sma(values: Sequence[Decimal], n: int) -> Series:
    out: Series = [None] * len(values)
    if n <= 0 or len(values) < n:
        return out
    with localcontext() as ctx:
        ctx.prec = _PRECISION
        window = sum(values[:n], Decimal(0))
        out[n - 1] = window / n
        for i in range(n, len(values)):
            window += values[i] - values[i - n]
            out[i] = window / n
    return out


def ema(values: Sequence[Decimal | None], n: int) -> Series:
    """EMA over a series that may start with Nones (e.g. EMA of MACD)."""
    out: Series = [None] * len(values)
    start = next((i for i, v in enumerate(values) if v is not None), None)
    if start is None or n <= 0 or len(values) - start < n:
        return out
    with localcontext() as ctx:
        ctx.prec = _PRECISION
        alpha = Decimal(2) / (n + 1)
        seed = values[start : start + n]
        level = sum((v for v in seed if v is not None), Decimal(0)) / n
        out[start + n - 1] = level
        for i in range(start + n, len(values)):
            v = values[i]
            if v is None:
                continue
            level = (v - level) * alpha + level
            out[i] = level
    return out


def rsi(closes: Sequence[Decimal], n: int = 14) -> Series:
    out: Series = [None] * len(closes)
    if len(closes) <= n:
        return out
    with localcontext() as ctx:
        ctx.prec = _PRECISION
        changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
        gains = [max(c, Decimal(0)) for c in changes]
        losses = [max(-c, Decimal(0)) for c in changes]
        avg_gain = sum(gains[:n], Decimal(0)) / n
        avg_loss = sum(losses[:n], Decimal(0)) / n

        def value(g: Decimal, loss: Decimal) -> Decimal:
            if loss == 0:
                return Decimal(100) if g > 0 else Decimal(50)
            return Decimal(100) - Decimal(100) / (1 + g / loss)

        out[n] = value(avg_gain, avg_loss)
        for i in range(n, len(changes)):
            avg_gain = (avg_gain * (n - 1) + gains[i]) / n
            avg_loss = (avg_loss * (n - 1) + losses[i]) / n
            out[i + 1] = value(avg_gain, avg_loss)
    return out


def macd(
    closes: Sequence[Decimal], fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[Series, Series, Series]:
    fast_ema, slow_ema = ema(closes, fast), ema(closes, slow)
    line: Series = [
        f - s if f is not None and s is not None else None
        for f, s in zip(fast_ema, slow_ema, strict=True)
    ]
    signal_line = ema(line, signal)
    hist: Series = [
        m - s if m is not None and s is not None else None
        for m, s in zip(line, signal_line, strict=True)
    ]
    return line, signal_line, hist


def bollinger(
    closes: Sequence[Decimal], n: int = 20, k: Decimal = Decimal(2)
) -> tuple[Series, Series, Series]:
    middle = sma(closes, n)
    upper: Series = [None] * len(closes)
    lower: Series = [None] * len(closes)
    with localcontext() as ctx:
        ctx.prec = _PRECISION
        for i in range(n - 1, len(closes)):
            mean = middle[i]
            if mean is None:
                continue
            window = closes[i - n + 1 : i + 1]
            variance = sum(((c - mean) ** 2 for c in window), Decimal(0)) / n
            std = variance.sqrt()
            upper[i] = mean + k * std
            lower[i] = mean - k * std
    return upper, middle, lower


def true_range(
    highs: Sequence[Decimal], lows: Sequence[Decimal], closes: Sequence[Decimal]
) -> list[Decimal]:
    ranges = []
    for i in range(len(closes)):
        if i == 0:
            ranges.append(highs[0] - lows[0])
            continue
        prev = closes[i - 1]
        ranges.append(max(highs[i] - lows[i], abs(highs[i] - prev), abs(lows[i] - prev)))
    return ranges


def atr(
    highs: Sequence[Decimal], lows: Sequence[Decimal], closes: Sequence[Decimal], n: int = 14
) -> Series:
    out: Series = [None] * len(closes)
    tr = true_range(highs, lows, closes)
    if len(tr) < n:
        return out
    with localcontext() as ctx:
        ctx.prec = _PRECISION
        level = sum(tr[:n], Decimal(0)) / n
        out[n - 1] = level
        for i in range(n, len(tr)):
            level = (level * (n - 1) + tr[i]) / n
            out[i] = level
    return out


def historical_volatility(
    closes: Sequence[Decimal], n: int, periods_per_year: int
) -> Decimal | None:
    """Annualized standard deviation of log returns over the last n periods (sample stdev)."""
    if len(closes) < n + 1:
        return None
    with localcontext() as ctx:
        ctx.prec = _PRECISION
        window = closes[-(n + 1) :]
        returns = [(window[i] / window[i - 1]).ln() for i in range(1, len(window))]
        mean = sum(returns, Decimal(0)) / n
        variance = sum(((r - mean) ** 2 for r in returns), Decimal(0)) / (n - 1)
        return variance.sqrt() * Decimal(periods_per_year).sqrt()
