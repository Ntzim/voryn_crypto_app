"""Pure alert conditions: (alert, observation, previous state) → (new state, event).

Edge semantics: an alert fires when its condition *becomes* true. The first evaluation
only records a baseline (no notification), so creating an alert whose condition already
holds does not fire immediately. Volume spikes fire once per qualifying closed candle.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.modules.alerts.models import AlertType

TREND_LABELS = {
    "uptrend": "tendência de alta",
    "downtrend": "tendência de baixa",
    "consolidation": "consolidação",
    "undefined": "tendência indefinida",
}
SIGNAL_LABELS = {
    "buy_potential": "Potencial de compra",
    "neutral": "Neutro",
    "attention": "Atenção",
    "sell_potential": "Potencial de venda",
}


@dataclass(frozen=True, slots=True)
class Observation:
    """Everything an alert can look at; fields are None when not applicable/unavailable."""

    symbol: str = ""
    price: Decimal | None = None
    currency: str = "USD"
    candle_time: str | None = None
    rsi: Decimal | None = None
    ema: dict[int, Decimal] = field(default_factory=dict)
    volume_ratio: Decimal | None = None
    trend: str | None = None
    signal: str | None = None
    signal_score: Decimal | None = None
    weight_pct: Decimal | None = None
    weight_symbol: str | None = None


@dataclass(frozen=True, slots=True)
class Event:
    title: str
    body: str
    #: stable id of this occurrence, part of the notification dedupe key
    key: str
    value: str | None = None


def _num(value: Decimal, digits: int = 2) -> str:
    text = f"{value:,.{digits}f}"
    return text.replace(",", "X").replace(".", ",").replace("X", ".")


def _money(value: Decimal, currency: str) -> str:
    prefix = "R$ " if currency == "BRL" else "US$ "
    digits = 2 if value >= 1 else min(12, max(4, -value.adjusted() + 3))
    return prefix + _num(value, digits)


def evaluate(
    alert_type: AlertType, params: dict[str, Any], obs: Observation, prev: dict[str, Any] | None
) -> tuple[dict[str, Any] | None, Event | None]:
    """Return the state to store and the event to notify (if any).

    A None state means "no data this time": keep the previous state, notify nothing.
    """
    match alert_type:
        case AlertType.PRICE_ABOVE | AlertType.PRICE_BELOW:
            if obs.price is None:
                return None, None
            target = Decimal(str(params["target"]))
            above = alert_type == AlertType.PRICE_ABOVE
            met = obs.price >= target if above else obs.price <= target
            event = None
            if met and prev is not None and not prev.get("met"):
                verb = "ultrapassou" if above else "caiu abaixo de"
                event = Event(
                    f"{obs.symbol} {verb} {_money(target, obs.currency)}",
                    f"{obs.symbol} {verb} {_money(target, obs.currency)}; cotação atual "
                    f"{_money(obs.price, obs.currency)}.",
                    key=f"cross:{target}",
                    value=str(obs.price),
                )
            return {"met": met}, event

        case AlertType.RSI_ABOVE | AlertType.RSI_BELOW:
            if obs.rsi is None or obs.candle_time is None:
                return None, None
            level = Decimal(str(params["level"]))
            above = alert_type == AlertType.RSI_ABOVE
            met = obs.rsi >= level if above else obs.rsi <= level
            event = None
            if met and prev is not None and not prev.get("met"):
                where = "acima" if above else "abaixo"
                event = Event(
                    f"RSI de {obs.symbol} {where} de {_num(level, 0)}",
                    f"O RSI(14) de {obs.symbol} fechou em {_num(obs.rsi, 1)}, {where} do limite "
                    f"de {_num(level, 0)}.",
                    key=f"candle:{obs.candle_time}",
                    value=str(obs.rsi),
                )
            return {"met": met}, event

        case AlertType.MA_CROSS:
            fast, slow = int(params["fast"]), int(params["slow"])
            if fast not in obs.ema or slow not in obs.ema or obs.candle_time is None:
                return None, None
            above = obs.ema[fast] > obs.ema[slow]
            direction = params.get("direction", "any")
            event = None
            crossed = prev is not None and "above" in prev and prev["above"] != above
            if crossed and (direction == "any" or (direction == "up") == above):
                kind = "positivo (alta)" if above else "negativo (baixa)"
                event = Event(
                    f"{obs.symbol}: cruzamento EMA {fast}/{slow}",
                    f"A EMA {fast} cruzou {'acima' if above else 'abaixo'} da EMA {slow} em "
                    f"{obs.symbol} — cruzamento {kind}.",
                    key=f"candle:{obs.candle_time}",
                )
            return {"above": above}, event

        case AlertType.VOLUME_SPIKE:
            if obs.volume_ratio is None or obs.candle_time is None:
                return None, None
            threshold = Decimal(str(params.get("ratio", "2")))
            event = None
            already = prev is not None and prev.get("candle") == obs.candle_time
            if obs.volume_ratio >= threshold and prev is not None and not already:
                event = Event(
                    f"Volume elevado em {obs.symbol}",
                    f"O último candle de {obs.symbol} teve volume {_num(obs.volume_ratio, 1)}× a "
                    f"média de 20 períodos (limite {_num(threshold, 1)}×).",
                    key=f"candle:{obs.candle_time}",
                    value=str(obs.volume_ratio),
                )
            fired_candle = obs.candle_time if event else (prev or {}).get("candle")
            return {"candle": fired_candle, "seen": obs.candle_time}, event

        case AlertType.TREND_CHANGE:
            if obs.trend is None or obs.candle_time is None:
                return None, None
            event = None
            goal = params.get("to")
            changed = prev is not None and prev.get("trend") and prev["trend"] != obs.trend
            if changed and prev is not None and (not goal or goal == obs.trend):
                before = TREND_LABELS.get(prev["trend"], prev["trend"])
                event = Event(
                    f"{obs.symbol}: mudança de tendência",
                    f"{obs.symbol} passou de {before} para "
                    f"{TREND_LABELS.get(obs.trend, obs.trend)}.",
                    key=f"candle:{obs.candle_time}",
                )
            return {"trend": obs.trend}, event

        case AlertType.SIGNAL_CHANGE:
            if obs.signal is None or obs.candle_time is None:
                return None, None
            event = None
            goal = params.get("to")
            changed = prev is not None and prev.get("signal") and prev["signal"] != obs.signal
            if changed and prev is not None and (not goal or goal == obs.signal):
                score = (
                    f" (score {_num(obs.signal_score, 0)})" if obs.signal_score is not None else ""
                )
                before = SIGNAL_LABELS.get(prev["signal"], prev["signal"])
                after = SIGNAL_LABELS.get(obs.signal, obs.signal)
                event = Event(
                    f"{obs.symbol}: sinal mudou para {after}",
                    f"O sinal de {obs.symbol} passou de {before} para {after}{score}. "
                    "Sinais são analíticos, não recomendações.",
                    key=f"candle:{obs.candle_time}",
                )
            return {"signal": obs.signal}, event

        case AlertType.CONCENTRATION:
            if obs.weight_pct is None:
                return None, None
            threshold = Decimal(str(params["threshold_pct"]))
            met = obs.weight_pct >= threshold
            event = None
            if met and prev is not None and not prev.get("met"):
                event = Event(
                    "Concentração da carteira",
                    f"{obs.weight_symbol} passou a representar {_num(obs.weight_pct, 1)}% da sua "
                    f"carteira (limite {_num(threshold, 0)}%).",
                    key=f"cross:{threshold}",
                    value=str(obs.weight_pct),
                )
            return {"met": met}, event
    raise ValueError(f"unsupported alert type {alert_type}")  # pragma: no cover
