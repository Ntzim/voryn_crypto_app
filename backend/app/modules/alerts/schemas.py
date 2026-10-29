import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal, Self

from pydantic import BaseModel, Field, model_validator

from app.modules.alerts.models import INDICATOR_TYPES, AlertType
from app.modules.market_data.providers.base import Timeframe
from app.modules.portfolio.schemas import AssetRef

EMA_PERIODS = (9, 21, 50, 200)
TREND_VALUES = ("uptrend", "downtrend", "consolidation", "undefined")
SIGNAL_VALUES = ("buy_potential", "neutral", "attention", "sell_potential")


def _decimal(
    params: dict[str, Any], key: str, low: Decimal, high: Decimal | None = None
) -> Decimal:
    try:
        value = Decimal(str(params[key]))
    except (KeyError, ArithmeticError, ValueError) as exc:
        raise ValueError(f"Informe o parâmetro “{key}”.") from exc
    if not value.is_finite() or value < low or (high is not None and value > high):
        bound = f"entre {low} e {high}" if high is not None else f"maior ou igual a {low}"
        raise ValueError(f"O parâmetro “{key}” deve ser {bound}.")
    return value


class AlertIn(BaseModel):
    type: AlertType
    asset_id: uuid.UUID | None = None
    timeframe: Timeframe | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    notify_email: bool = True
    cooldown_minutes: int = Field(default=360, ge=15, le=10080)
    is_active: bool = True

    @model_validator(mode="after")
    def _validate(self) -> Self:
        p = self.params
        t = self.type
        if t != AlertType.CONCENTRATION and self.asset_id is None:
            raise ValueError("Selecione o ativo.")
        if t in INDICATOR_TYPES:
            self.timeframe = self.timeframe or "1d"
        else:
            self.timeframe = None
        clean: dict[str, Any] = {}
        if t in (AlertType.PRICE_ABOVE, AlertType.PRICE_BELOW):
            target = _decimal(p, "target", Decimal("0.00000001"))
            currency = p.get("currency", "USD")
            if currency not in ("USD", "BRL"):
                raise ValueError("Moeda deve ser USD ou BRL.")
            clean = {"target": str(target), "currency": currency}
        elif t in (AlertType.RSI_ABOVE, AlertType.RSI_BELOW):
            clean = {"level": str(_decimal(p, "level", Decimal(1), Decimal(99)))}
        elif t == AlertType.MA_CROSS:
            fast, slow = int(p.get("fast", 50)), int(p.get("slow", 200))
            if fast not in EMA_PERIODS or slow not in EMA_PERIODS or fast >= slow:
                raise ValueError(
                    "Escolha médias de 9, 21, 50 ou 200 períodos, com a rápida menor que a lenta."
                )
            direction = p.get("direction", "any")
            if direction not in ("up", "down", "any"):
                raise ValueError("Direção inválida.")
            clean = {"fast": fast, "slow": slow, "direction": direction}
        elif t == AlertType.VOLUME_SPIKE:
            clean = {
                "ratio": str(
                    _decimal({"ratio": p.get("ratio", "2")}, "ratio", Decimal("1.2"), Decimal(20))
                )
            }
        elif t == AlertType.TREND_CHANGE:
            goal = p.get("to")
            if goal is not None and goal not in TREND_VALUES:
                raise ValueError("Tendência de destino inválida.")
            clean = {"to": goal} if goal else {}
        elif t == AlertType.SIGNAL_CHANGE:
            goal = p.get("to")
            if goal is not None and goal not in SIGNAL_VALUES:
                raise ValueError("Classificação de destino inválida.")
            clean = {"to": goal} if goal else {}
        elif t == AlertType.CONCENTRATION:
            clean = {"threshold_pct": str(_decimal(p, "threshold_pct", Decimal(5), Decimal(100)))}
        self.params = clean
        return self


class AlertOut(BaseModel):
    id: uuid.UUID
    type: AlertType
    asset: AssetRef | None
    timeframe: Timeframe | None
    params: dict[str, Any]
    notify_email: bool
    cooldown_minutes: int
    is_active: bool
    description: str
    last_evaluated_at: datetime | None
    last_triggered_at: datetime | None
    trigger_count: int
    created_at: datetime


class NotificationOut(BaseModel):
    id: int
    kind: Literal["alert", "system"]
    title: str
    body: str
    data: dict[str, Any]
    alert_id: uuid.UUID | None
    created_at: datetime
    read_at: datetime | None


class NotificationListOut(BaseModel):
    items: list[NotificationOut]
    unread: int
    total: int
