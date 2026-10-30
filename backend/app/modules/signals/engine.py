"""Opportunity signal engine — transparent, rule-based scoring (no prediction, no AI).

Six components, each scored 0–100 (50 = neutral), combined with the strategy's weights:

| Component            | Rule (summary)                                                          |
|----------------------|-------------------------------------------------------------------------|
| Trend                | 50 + 50 × (trend score ÷ criteria available)                           |
| Momentum             | mean of MACD (cross/histogram) and RSI (mean reversion at extremes,     |
|                      | momentum in the middle band) sub-scores                                 |
| Volume               | relative volume × direction of the last closed candle                   |
| Volatility           | 80 − 0.6 × Bollinger-width percentile (calmer ⇒ lower risk ⇒ higher)  |
| Support/resistance   | 30 + 50 × room to resistance ÷ (room to support + room to resistance)  |
| Market               | mean of breadth (advancers %) and Bitcoin's trend                       |

Classification (thresholds come from the strategy):
- stale, incomplete or anomalous data (signals.quality) → "attention", never buy/sell;
- score ≥ buy threshold and trend not bearish → "buy_potential";
- score ≤ sell threshold, or bearish trend with score ≤ sell threshold + 10 → "sell_potential";
- contradictory evidence (trend vs momentum gap ≥ 40, RSI ≥ 75 or ≤ 25, volatility
  score ≤ 30) → "attention";
- otherwise → "neutral".

The score measures how many favourable conditions are aligned. It is NOT a probability
of profit, and the classification is an analytical signal, not personalised advice.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

from app.modules.technical_analysis.levels import Level
from app.modules.technical_analysis.schemas import Snapshot
from app.modules.technical_analysis.trend import TrendResult

Classification = Literal["buy_potential", "neutral", "attention", "sell_potential"]
COMPONENTS = ("trend", "momentum", "volume", "volatility", "levels", "market")

DEFAULT_WEIGHTS: dict[str, Decimal] = {
    "trend": Decimal("0.25"),
    "momentum": Decimal("0.20"),
    "volume": Decimal("0.15"),
    "volatility": Decimal("0.15"),
    "levels": Decimal("0.15"),
    "market": Decimal("0.10"),
}
DEFAULT_THRESHOLDS: dict[str, Decimal] = {"buy": Decimal(65), "sell": Decimal(35)}


@dataclass(frozen=True, slots=True)
class MarketContext:
    #: share of tracked assets up in 24h, 0–100
    breadth_pct: Decimal | None
    btc_trend: str | None


@dataclass(frozen=True, slots=True)
class Component:
    key: str
    score: Decimal
    weight: Decimal
    detail: str


@dataclass(slots=True)
class SignalResult:
    score: Decimal
    classification: Classification
    components: list[Component]
    justification: str
    risks: list[str] = field(default_factory=list)
    invalidation: list[str] = field(default_factory=list)


def _sentence(text: str) -> str:
    """Capitalize only the first letter (str.capitalize would lowercase "MACD")."""
    return text[:1].upper() + text[1:]


def _clamp(value: Decimal) -> Decimal:
    return max(Decimal(0), min(Decimal(100), value))


def _fmt(value: Decimal, digits: int = 1) -> str:
    return f"{value:,.{digits}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _money(value: Decimal) -> str:
    # Significant digits for sub-unit prices (micro-caps like 0,00000512).
    digits = 2 if value >= 1 else min(12, max(4, -value.adjusted() + 3))
    return "US$ " + _fmt(value, digits)


def _trend(trend: TrendResult) -> Component:
    score = Decimal(50) if not trend.available else 50 + Decimal(50) * trend.score / trend.available
    label = {
        "uptrend": "tendência de alta",
        "downtrend": "tendência de baixa",
        "consolidation": "consolidação",
        "undefined": "tendência indefinida",
    }[trend.classification]
    return Component(
        "trend",
        _clamp(score),
        Decimal(0),
        f"{_sentence(label)} (saldo {trend.score:+d}/{trend.available}).",
    )


def _momentum(s: Snapshot) -> Component:
    parts: list[Decimal] = []
    notes: list[str] = []
    if s.macd_hist is not None:
        if s.macd_cross == "bullish":
            parts.append(Decimal(80))
            notes.append("cruzamento positivo recente do MACD")
        elif s.macd_cross == "bearish":
            parts.append(Decimal(20))
            notes.append("cruzamento negativo recente do MACD")
        else:
            positive = s.macd_hist > 0
            parts.append(Decimal(65) if positive else Decimal(35))
            notes.append(f"histograma do MACD {'positivo' if positive else 'negativo'}")
    if s.rsi is not None:
        r = s.rsi
        if r >= 70:
            parts.append(Decimal(25))
            notes.append(f"RSI {_fmt(r)} em sobrecompra")
        elif r <= 30:
            parts.append(Decimal(70))
            notes.append(f"RSI {_fmt(r)} em sobrevenda (potencial de reação, com risco)")
        elif r >= 55:
            parts.append(Decimal(62))
            notes.append(f"RSI {_fmt(r)} com força compradora")
        elif r <= 45:
            parts.append(Decimal(40))
            notes.append(f"RSI {_fmt(r)} com força vendedora")
        else:
            parts.append(Decimal(50))
            notes.append(f"RSI {_fmt(r)} neutro")
    score = sum(parts, Decimal(0)) / len(parts) if parts else Decimal(50)
    return Component(
        "momentum",
        score,
        Decimal(0),
        _sentence("; ".join(notes) or "Momentum indisponível") + ".",
    )


def _volume(s: Snapshot, last_up: bool) -> Component:
    ratio = s.volume_ratio
    if ratio is None:
        return Component("volume", Decimal(50), Decimal(0), "Volume médio indisponível.")
    direction = "alta" if last_up else "baixa"
    if ratio >= Decimal("1.5"):
        score, text = (Decimal(75), "reforça") if last_up else (Decimal(25), "reforça")
        detail = f"Volume {_fmt(ratio, 2)}× a média {text} o candle de {direction}."
    elif ratio >= 1:
        score = Decimal(58) if last_up else Decimal(42)
        detail = f"Volume {_fmt(ratio, 2)}× a média, levemente acima, em candle de {direction}."
    elif ratio < Decimal("0.7"):
        score = Decimal(45)
        detail = f"Volume fraco ({_fmt(ratio, 2)}× a média): pouca participação."
    else:
        score = Decimal(50)
        detail = f"Volume dentro da média ({_fmt(ratio, 2)}×)."
    return Component("volume", score, Decimal(0), detail)


def _volatility(bandwidth_percentile: Decimal | None, s: Snapshot) -> Component:
    if bandwidth_percentile is None:
        return Component(
            "volatility", Decimal(50), Decimal(0), "Volatilidade relativa indisponível."
        )
    score = _clamp(Decimal(80) - Decimal("0.6") * bandwidth_percentile)
    level = (
        "baixa"
        if bandwidth_percentile <= 30
        else "elevada"
        if bandwidth_percentile >= 70
        else "moderada"
    )
    atr = f" ATR de {_fmt(s.atr_pct, 2)}% por candle." if s.atr_pct is not None else ""
    percentile = _fmt(bandwidth_percentile, 0)
    return Component(
        "volatility",
        score,
        Decimal(0),
        f"Volatilidade {level} em relação aos últimos 100 candles (percentil {percentile}).{atr}",
    )


def _levels(
    price: Decimal, supports: list[Level], resistances: list[Level], atr: Decimal | None
) -> Component:
    if not supports or not resistances:
        side = "suporte" if not supports else "resistência"
        return Component(
            "levels", Decimal(50), Decimal(0), f"Sem {side} identificado próximo ao preço."
        )
    support, resistance = supports[0].price, resistances[0].price
    room_up, room_down = resistance - price, price - support
    total = room_up + room_down
    score = 30 + Decimal(50) * room_up / total if total > 0 else Decimal(50)
    detail = (
        f"Suporte em {_money(support)} ({_fmt(room_down / price * 100)}% abaixo) e resistência em "
        f"{_money(resistance)} ({_fmt(room_up / price * 100)}% acima)."
    )
    return Component("levels", _clamp(score), Decimal(0), detail)


def _market(ctx: MarketContext) -> Component:
    parts: list[Decimal] = []
    notes: list[str] = []
    if ctx.breadth_pct is not None:
        parts.append(ctx.breadth_pct)
        notes.append(f"{_fmt(ctx.breadth_pct, 0)}% dos principais ativos em alta em 24h")
    if ctx.btc_trend:
        parts.append(
            {"uptrend": Decimal(70), "downtrend": Decimal(30)}.get(ctx.btc_trend, Decimal(50))
        )
        btc = {"uptrend": "alta", "downtrend": "baixa", "consolidation": "consolidação"}.get(
            ctx.btc_trend, "indefinida"
        )
        notes.append(
            f"Bitcoin em tendência {btc}" if btc != "consolidação" else "Bitcoin em consolidação"
        )
    score = sum(parts, Decimal(0)) / len(parts) if parts else Decimal(50)
    return Component(
        "market",
        _clamp(score),
        Decimal(0),
        _sentence("; ".join(notes) or "Contexto de mercado indisponível") + ".",
    )


def evaluate(
    *,
    snapshot: Snapshot,
    trend: TrendResult,
    supports: list[Level],
    resistances: list[Level],
    bandwidth_percentile: Decimal | None,
    last_candle_up: bool,
    market: MarketContext,
    stale: bool,
    weights: dict[str, Decimal] | None = None,
    thresholds: dict[str, Decimal] | None = None,
    quality_issue: str | None = None,
) -> SignalResult:
    """`quality_issue` (from signals.quality) suspends buy/sell like stale data does."""
    weights = weights or DEFAULT_WEIGHTS
    thresholds = thresholds or DEFAULT_THRESHOLDS
    total_weight = sum((weights[k] for k in COMPONENTS), Decimal(0))
    price = snapshot.close

    raw = [
        _trend(trend),
        _momentum(snapshot),
        _volume(snapshot, last_candle_up),
        _volatility(bandwidth_percentile, snapshot),
        _levels(price, supports, resistances, snapshot.atr),
        _market(market),
    ]
    components = [
        Component(c.key, c.score.quantize(Decimal("0.1")), weights[c.key] / total_weight, c.detail)
        for c in raw
    ]
    score = sum((c.score * c.weight for c in components), Decimal(0)).quantize(Decimal("0.1"))
    by_key = {c.key: c for c in components}

    risks: list[str] = []
    if resistances and (resistances[0].price - price) / price * 100 < 3:
        risks.append(f"Proximidade de resistência relevante em {_money(resistances[0].price)}.")
    if snapshot.rsi is not None and snapshot.rsi >= 70:
        risks.append("RSI em sobrecompra: movimentos de correção são frequentes nessa condição.")
    if snapshot.rsi is not None and snapshot.rsi <= 30:
        risks.append("RSI em sobrevenda: a queda pode continuar antes de qualquer reação.")
    if by_key["volatility"].score <= 30:
        risks.append("Volatilidade elevada: oscilações amplas aumentam o risco de perdas.")
    if trend.classification == "downtrend":
        risks.append("Tendência principal de baixa.")
    if by_key["market"].score < 40:
        risks.append("Mercado em geral desfavorável.")
    if stale:
        risks.append("Dados de preço desatualizados: o sinal pode não refletir o mercado atual.")
    elif quality_issue:
        risks.append(f"Qualidade dos dados insuficiente: {quality_issue}")

    contradictory = (
        abs(by_key["trend"].score - by_key["momentum"].score) >= 40
        or (snapshot.rsi is not None and (snapshot.rsi >= 75 or snapshot.rsi <= 25))
        or by_key["volatility"].score <= 30
    )
    classification: Classification
    if stale or quality_issue:
        classification = "attention"
    elif score >= thresholds["buy"] and trend.classification != "downtrend":
        classification = "buy_potential"
    elif score <= thresholds["sell"] or (
        trend.classification == "downtrend" and score <= thresholds["sell"] + 10
    ):
        classification = "sell_potential"
    elif contradictory:
        classification = "attention"
    else:
        classification = "neutral"

    invalidation: list[str] = []
    if classification == "buy_potential":
        if supports:
            invalidation.append(f"Fechamento abaixo do suporte em {_money(supports[0].price)}.")
        if snapshot.ema50 is not None:
            invalidation.append(f"Perda da EMA 50 ({_money(snapshot.ema50)}) em fechamento.")
    elif classification == "sell_potential":
        if resistances:
            invalidation.append(
                f"Fechamento acima da resistência em {_money(resistances[0].price)}."
            )
        if snapshot.ema50 is not None:
            invalidation.append(f"Recuperação da EMA 50 ({_money(snapshot.ema50)}) em fechamento.")
    else:
        invalidation.append("Sem cenário direcional: reavaliar a cada novo candle fechado.")

    strongest = sorted(components, key=lambda c: abs(c.score - 50) * c.weight, reverse=True)[:3]
    intro = {
        "buy_potential": "Os indicadores sugerem uma possível oportunidade de entrada.",
        "sell_potential": (
            "Os indicadores sugerem enfraquecimento e possível oportunidade de saída."
        ),
        "attention": "Há sinais contraditórios ou aumento relevante de risco.",
        "neutral": "Não há evidência suficiente para indicar uma direção.",
    }[classification]
    justification = intro + " " + " ".join(c.detail for c in strongest)
    if stale:
        justification = "Dados desatualizados — sinal suspenso. " + justification
    elif quality_issue:
        justification = "Dados inconsistentes ou incompletos — sinal suspenso. " + justification

    return SignalResult(score, classification, components, justification, risks, invalidation)
