"""Indicators against published reference values and exact mathematical properties."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest

from app.modules.market_data.providers.base import Candle
from app.modules.technical_analysis import indicators as ind
from app.modules.technical_analysis.levels import detect_levels
from app.modules.technical_analysis.service import analyze
from app.modules.technical_analysis.trend import TrendInputs, classify


def decimals(*values: float) -> list[D]:
    return [D(str(v)) for v in values]


# StockCharts ChartSchool, "Relative Strength Index (RSI)" worked example (Wilder smoothing).
# Closes from the original "cs-rsi" spreadsheet (4 decimals).
RSI_CLOSES = decimals(
    44.3389, 44.0902, 44.1497, 43.6124, 44.3278, 44.8264, 45.0955, 45.4245, 45.8433, 46.0826,
    45.8931, 46.0328, 45.6140, 46.2820, 46.2820, 46.0028, 46.0328, 46.4116, 46.2222, 45.6439,
    46.2122, 46.2521, 45.7137, 46.4515, 45.7835, 45.3548, 44.0288, 44.1783, 44.2181, 44.5672,
    43.4205, 42.6628, 43.1314,
)  # fmt: skip
RSI_EXPECTED = decimals(
    70.53, 66.32, 66.55, 69.41, 66.36, 57.97, 62.93, 63.26, 56.06, 62.38, 54.71, 50.42, 39.99,
    41.46, 41.87, 45.46, 37.30, 33.08, 37.77,
)  # fmt: skip


def test_rsi_matches_wilder_reference() -> None:
    values = ind.rsi(RSI_CLOSES, 14)
    assert values[:14] == [None] * 14
    computed = [v for v in values[14:] if v is not None]
    assert len(computed) == len(RSI_EXPECTED)
    for got, expected in zip(computed, RSI_EXPECTED, strict=True):
        assert abs(got - expected) < D("0.01"), (got, expected)


# StockCharts ChartSchool, "Moving Averages" 10-day EMA example (SMA-seeded).
EMA_CLOSES = decimals(
    22.27, 22.19, 22.08, 22.17, 22.18, 22.13, 22.23, 22.43, 22.24, 22.29, 22.15, 22.39, 22.38,
    22.61, 23.36, 24.05, 23.75, 23.83, 23.95, 23.63, 23.82, 23.87, 23.65, 23.19, 23.10, 23.33,
    22.68, 23.10, 22.40, 22.17,
)  # fmt: skip
EMA_EXPECTED = decimals(
    22.22, 22.21, 22.24, 22.27, 22.33, 22.52, 22.80, 22.97, 23.13, 23.28, 23.34, 23.43, 23.51,
    23.53, 23.47, 23.40, 23.39, 23.26, 23.23, 23.08, 22.92,
)  # fmt: skip


def test_ema_matches_reference() -> None:
    values = ind.ema(EMA_CLOSES, 10)
    computed = [v for v in values if v is not None]
    for got, expected in zip(computed, EMA_EXPECTED, strict=True):
        assert abs(got - expected) < D("0.01"), (got, expected)


def test_sma_and_bollinger_population_stdev() -> None:
    closes = [D(i) for i in range(1, 21)]
    assert ind.sma(closes, 20)[-1] == D("10.5")
    upper, middle, lower = ind.bollinger(closes, 20)
    # Population stdev of 1..20 = sqrt((20² − 1) / 12)
    std = (D(399) / D(12)).sqrt()
    assert middle[-1] == D("10.5")
    assert abs(upper[-1] - (D("10.5") + 2 * std)) < D("1e-20")  # type: ignore[operator]
    assert abs(lower[-1] - (D("10.5") - 2 * std)) < D("1e-20")  # type: ignore[operator]


def test_macd_of_linear_series_is_exactly_the_lag_difference() -> None:
    # For x_t = t an SMA-seeded EMA(n) equals t − (n−1)/2, so MACD = 12.5 − 5.5 = 7.
    closes = [D(t) for t in range(80)]
    line, signal, hist = ind.macd(closes)
    assert line[24] is None and line[25] == D(7)
    assert signal[-1] == D(7) and hist[-1] == 0


def test_atr_of_constant_range_equals_range() -> None:
    highs = [D(110)] * 30
    lows = [D(100)] * 30
    closes = [D(105)] * 30
    assert ind.atr(highs, lows, closes, 14)[-1] == D(10)


def test_historical_volatility_of_constant_growth_is_zero() -> None:
    closes = [D(100) * D("1.01") ** i for i in range(40)]
    vol = ind.historical_volatility(closes, 30, 365)
    assert vol is not None and vol < D("1e-20")


# --------------------------------------------------------------------------- trend & levels

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def candles_from(closes: list[D], spread: D = D("0.01")) -> list[Candle]:
    out = []
    for i, c in enumerate(closes):
        prev = closes[i - 1] if i else c
        out.append(
            Candle(
                open_time=T0 + timedelta(days=i),
                open=prev,
                high=max(prev, c) * (1 + spread),
                low=min(prev, c) * (1 - spread),
                close=c,
                volume=D(1000),
                quote_volume=D(1000) * c,
                closed=True,
            )
        )
    return out


def test_rising_market_is_classified_as_uptrend_with_justification() -> None:
    closes = [D(100) * D("1.01") ** i + (D(1) if i % 2 else D(0)) for i in range(250)]
    result = analyze(candles_from(closes), "1d")
    assert result.trend is not None
    assert result.trend.classification == "uptrend"
    assert result.trend.score >= 3
    assert any("EMA 200" in c.name and c.vote == "bullish" for c in result.trend.criteria)


def test_falling_market_is_downtrend() -> None:
    closes = [D(500) * D("0.99") ** i + (D(1) if i % 2 else D(0)) for i in range(250)]
    result = analyze(candles_from(closes), "1d")
    assert result.trend is not None and result.trend.classification == "downtrend"


def test_short_history_is_undefined() -> None:
    result = analyze(candles_from([D(100 + i) for i in range(40)]), "1d")
    assert result.trend is not None
    assert result.trend.classification == "undefined"
    assert "insuficiente" in result.trend.summary


def test_consolidation_rule() -> None:
    inputs = TrendInputs(
        closed_candles=200, close=D(100), ema21=D("100.1"), ema50=D(100), ema50_prev=D("100.05"),
        ema200=D(95), macd=D("0.1"), macd_signal=D("0.2"), rsi=D(50), atr_pct=D(2),
        bandwidth_percentile=D(20),
    )  # fmt: skip
    result = classify(inputs)
    assert result.classification == "consolidation", result.summary


def test_levels_cluster_repeated_swings() -> None:
    pattern = [D(x) for x in (100, 104, 108, 110, 107, 103, 98, 94, 90, 93, 97, 101)]
    closes = pattern * 4 + [D(100)]
    flat = [
        Candle(T0 + timedelta(days=i), c, c, c, c, D(1), c, closed=True)
        for i, c in enumerate(closes)
    ]
    supports, resistances = detect_levels(flat, atr_value=D(2))
    assert resistances and abs(resistances[0].price - D(110)) < D(1)
    assert resistances[0].touches >= 3
    assert supports and abs(supports[0].price - D(90)) < D(1)


def test_live_candle_is_excluded_from_indicators() -> None:
    candles = candles_from([D(100 + i) for i in range(30)])
    live = Candle(T0 + timedelta(days=30), D(129), D(500), D(1), D(400), D(1), D(1), closed=False)
    result = analyze([*candles, live], "1d")
    assert result.series.sma20[-1] is None  # aligned, but not computed on the live candle
    assert result.snapshot is not None and result.snapshot.close == D(129)


@pytest.mark.parametrize("n", [0, 50])
def test_insufficient_data_returns_all_none(n: int) -> None:
    assert ind.sma([D(1)] * 10, n) == [None] * 10
