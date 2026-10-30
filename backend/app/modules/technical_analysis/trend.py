"""Trend classification from multiple indicators, with a human-readable justification.

Each criterion casts a vote (+1 bullish, −1 bearish, 0 neutral/unavailable):

1. Close vs EMA 200 — long-term regime.
2. Close vs EMA 50 — medium-term regime.
3. EMA 21 vs EMA 50 — moving-average alignment.
4. EMA 50 slope over 10 candles, compared with half the ATR% — flat when smaller.
5. MACD vs signal, and MACD sign — momentum.
6. RSI(14) above 55 / below 45 — momentum regime.

Classification:
- Uptrend: score ≥ +3, close above EMA 50, EMA 50 slope not falling.
- Downtrend: score ≤ −3, close below EMA 50, EMA 50 slope not rising.
- Consolidation: EMA 50 flat, Bollinger bandwidth in the lowest 40% of the last 100
  candles, and |score| ≤ 2.
- Undefined: anything else (mixed signals) or fewer than 60 closed candles.

Confidence = |score| / criteria available (≥ 0.8 high, ≥ 0.5 moderate, else low).
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

Classification = Literal["uptrend", "downtrend", "consolidation", "undefined"]
Vote = Literal["bullish", "bearish", "neutral"]

MIN_CANDLES = 60


@dataclass(frozen=True, slots=True)
class Criterion:
    name: str
    vote: Vote
    detail: str


@dataclass(slots=True)
class TrendResult:
    classification: Classification
    score: int
    available: int
    confidence: Literal["high", "moderate", "low"]
    criteria: list[Criterion] = field(default_factory=list)
    summary: str = ""


@dataclass(frozen=True, slots=True)
class TrendInputs:
    closed_candles: int
    close: Decimal
    ema21: Decimal | None
    ema50: Decimal | None
    ema50_prev: Decimal | None  # EMA 50 ten candles ago
    ema200: Decimal | None
    macd: Decimal | None
    macd_signal: Decimal | None
    rsi: Decimal | None
    atr_pct: Decimal | None
    bandwidth_percentile: Decimal | None  # 0–100, current vs last 100 candles


def _fmt(value: Decimal, digits: int = 1) -> str:
    return f"{value:.{digits}f}".replace(".", ",")


def classify(x: TrendInputs) -> TrendResult:
    criteria: list[Criterion] = []

    def add(name: str, vote: Vote, detail: str) -> None:
        criteria.append(Criterion(name, vote, detail))

    if x.ema200 is not None:
        above = x.close > x.ema200
        add(
            "EMA 200",
            "bullish" if above else "bearish",
            f"Preço {'acima' if above else 'abaixo'} da média de 200 períodos "
            "(tendência de longo prazo).",
        )
    if x.ema50 is not None:
        above = x.close > x.ema50
        add(
            "EMA 50",
            "bullish" if above else "bearish",
            f"Preço {'acima' if above else 'abaixo'} da média de 50 períodos.",
        )
    if x.ema21 is not None and x.ema50 is not None:
        up = x.ema21 > x.ema50
        add(
            "Alinhamento de médias",
            "bullish" if up else "bearish",
            f"EMA 21 {'acima' if up else 'abaixo'} da EMA 50.",
        )

    slope_state: Vote = "neutral"
    if x.ema50 is not None and x.ema50_prev and x.atr_pct is not None:
        slope = (x.ema50 / x.ema50_prev - 1) * 100
        threshold = x.atr_pct / 2
        if slope > threshold:
            slope_state = "bullish"
        elif slope < -threshold:
            slope_state = "bearish"
        label = {"bullish": "ascendente", "bearish": "descendente", "neutral": "lateral"}[
            slope_state
        ]
        add(
            "Inclinação da EMA 50",
            slope_state,
            f"EMA 50 {label} ({_fmt(slope, 2)}% em 10 candles; limiar ±{_fmt(threshold, 2)}%).",
        )

    if x.macd is not None and x.macd_signal is not None:
        if x.macd > x.macd_signal and x.macd > 0:
            add("MACD", "bullish", "MACD acima da linha de sinal e positivo (momentum de alta).")
        elif x.macd < x.macd_signal and x.macd < 0:
            add("MACD", "bearish", "MACD abaixo da linha de sinal e negativo (momentum de baixa).")
        else:
            add("MACD", "neutral", "MACD e linha de sinal sem direção conjunta.")

    if x.rsi is not None:
        if x.rsi > 55:
            add("RSI", "bullish", f"RSI em {_fmt(x.rsi)}: compradores predominam.")
        elif x.rsi < 45:
            add("RSI", "bearish", f"RSI em {_fmt(x.rsi)}: vendedores predominam.")
        else:
            add("RSI", "neutral", f"RSI em {_fmt(x.rsi)}: zona neutra.")

    score = sum(1 if c.vote == "bullish" else -1 if c.vote == "bearish" else 0 for c in criteria)
    available = len(criteria)
    ratio = Decimal(abs(score)) / available if available else Decimal(0)
    confidence: Literal["high", "moderate", "low"] = (
        "high" if ratio >= Decimal("0.8") else "moderate" if ratio >= Decimal("0.5") else "low"
    )
    result = TrendResult("undefined", score, available, confidence, criteria)

    if x.closed_candles < MIN_CANDLES or x.ema50 is None:
        result.confidence = "low"
        result.summary = (
            f"Histórico insuficiente para classificar a tendência ({x.closed_candles} candles "
            f"fechados; mínimo {MIN_CANDLES})."
        )
        return result

    if score >= 3 and x.close > x.ema50 and slope_state != "bearish":
        result.classification = "uptrend"
        result.summary = (
            f"Tendência de alta: {score:+d} de {available} critérios apontam para cima."
        )
    elif score <= -3 and x.close < x.ema50 and slope_state != "bullish":
        result.classification = "downtrend"
        result.summary = (
            f"Tendência de baixa: {score:+d} de {available} critérios apontam para baixo."
        )
    elif (
        slope_state == "neutral"
        and x.bandwidth_percentile is not None
        and x.bandwidth_percentile <= 40
        and abs(score) <= 2
    ):
        result.classification = "consolidation"
        result.summary = (
            "Consolidação: média de 50 períodos lateral e bandas de Bollinger estreitas "
            f"(largura no percentil {_fmt(x.bandwidth_percentile, 0)} dos últimos 100 candles)."
        )
    else:
        result.summary = f"Tendência indefinida: sinais mistos (saldo {score:+d} de {available})."
    return result
