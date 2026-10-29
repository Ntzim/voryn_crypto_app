"""Alerts: CRUD, periodic evaluation and notifications."""

import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import rate_limit
from app.core.errors import AppError, NotFoundError
from app.core.logging import get_logger
from app.modules.alerts import conditions
from app.modules.alerts.channels import CHANNELS
from app.modules.alerts.models import INDICATOR_TYPES, Alert, AlertType, Notification
from app.modules.alerts.schemas import AlertIn, AlertOut, NotificationOut
from app.modules.market_data import candles as candle_service
from app.modules.market_data import service as market
from app.modules.market_data.models import Cryptocurrency
from app.modules.market_data.providers.base import CandleProvider, ProviderError
from app.modules.portfolio.schemas import AssetRef
from app.modules.technical_analysis.service import analyze
from app.modules.users.models import User

logger = get_logger(__name__)

MAX_ALERTS = 50
IN_APP_PER_HOUR = 30

_TYPE_TEXT = {
    AlertType.PRICE_ABOVE: "Preço acima de {target} {currency}",
    AlertType.PRICE_BELOW: "Preço abaixo de {target} {currency}",
    AlertType.RSI_ABOVE: "RSI acima de {level}",
    AlertType.RSI_BELOW: "RSI abaixo de {level}",
    AlertType.MA_CROSS: "Cruzamento EMA {fast}/{slow}",
    AlertType.VOLUME_SPIKE: "Volume ≥ {ratio}× a média",
    AlertType.TREND_CHANGE: "Mudança de tendência",
    AlertType.SIGNAL_CHANGE: "Mudança no sinal de oportunidade",
    AlertType.CONCENTRATION: "Concentração ≥ {threshold_pct}% da carteira",
}


def utcnow() -> datetime:
    return datetime.now(UTC)


def describe(alert: Alert, symbol: str | None) -> str:
    text = _TYPE_TEXT[alert.type].format(**{k: v for k, v in alert.params.items() if v is not None})
    if alert.type == AlertType.MA_CROSS and alert.params.get("direction") in ("up", "down"):
        text += " (alta)" if alert.params["direction"] == "up" else " (baixa)"
    goal = alert.params.get("to")
    if goal:
        label = conditions.TREND_LABELS.get(goal) or conditions.SIGNAL_LABELS.get(goal, goal)
        text += f" para {label}"
    where = (
        f"{symbol} · "
        if symbol
        else ("Qualquer ativo · " if alert.type == AlertType.CONCENTRATION else "")
    )
    tf = f" · {alert.timeframe}" if alert.timeframe else ""
    return f"{where}{text}{tf}"


# --------------------------------------------------------------------------- CRUD


async def list_alerts(db: AsyncSession, user_id: uuid.UUID) -> list[AlertOut]:
    alerts = list(
        (
            await db.execute(
                select(Alert).where(Alert.user_id == user_id).order_by(Alert.created_at.desc())
            )
        ).scalars()
    )
    return await _out(db, alerts)


async def _out(db: AsyncSession, alerts: list[Alert]) -> list[AlertOut]:
    cryptos = await market.cryptos_by_id(
        db, [a.cryptocurrency_id for a in alerts if a.cryptocurrency_id]
    )
    out = []
    for a in alerts:
        c = cryptos.get(a.cryptocurrency_id) if a.cryptocurrency_id else None
        out.append(
            AlertOut(
                id=a.id,
                type=a.type,
                asset=AssetRef(
                    id=c.id, slug=c.source_id, symbol=c.symbol, name=c.name, image_url=c.image_url
                )
                if c
                else None,
                timeframe=a.timeframe,
                params=a.params,
                notify_email=a.notify_email,
                cooldown_minutes=a.cooldown_minutes,
                is_active=a.is_active,
                description=describe(a, c.symbol if c else None),
                last_evaluated_at=a.last_evaluated_at,
                last_triggered_at=a.last_triggered_at,
                trigger_count=a.trigger_count,
                created_at=a.created_at,
            )
        )
    return out


async def get_owned(db: AsyncSession, user_id: uuid.UUID, alert_id: uuid.UUID) -> Alert:
    alert = (
        await db.execute(select(Alert).where(Alert.id == alert_id, Alert.user_id == user_id))
    ).scalar_one_or_none()
    if alert is None:
        raise NotFoundError("Alerta não encontrado.")
    return alert


def _apply(alert: Alert, data: AlertIn) -> None:
    changed = (
        alert.type != data.type
        or alert.cryptocurrency_id != data.asset_id
        or alert.timeframe != data.timeframe
        or alert.params != data.params
    )
    alert.type = data.type
    alert.cryptocurrency_id = data.asset_id
    alert.timeframe = data.timeframe
    alert.params = data.params
    alert.notify_email = data.notify_email
    alert.cooldown_minutes = data.cooldown_minutes
    alert.is_active = data.is_active
    if changed:
        # A different condition starts from a fresh baseline.
        alert.last_state = None


async def create(db: AsyncSession, user_id: uuid.UUID, data: AlertIn) -> AlertOut:
    count = await db.scalar(select(func.count()).where(Alert.user_id == user_id)) or 0
    if count >= MAX_ALERTS:
        raise AppError(f"Limite de {MAX_ALERTS} alertas atingido.", code="limit_reached")
    if data.asset_id and await db.get(Cryptocurrency, data.asset_id) is None:
        raise NotFoundError("Ativo não encontrado.")
    alert = Alert(user_id=user_id, created_at=utcnow(), trigger_count=0)
    _apply(alert, data)
    db.add(alert)
    await db.commit()
    return (await _out(db, [alert]))[0]


async def update_alert(db: AsyncSession, alert: Alert, data: AlertIn) -> AlertOut:
    if data.asset_id and await db.get(Cryptocurrency, data.asset_id) is None:
        raise NotFoundError("Ativo não encontrado.")
    _apply(alert, data)
    await db.commit()
    return (await _out(db, [alert]))[0]


async def delete_alert(db: AsyncSession, alert: Alert) -> None:
    await db.delete(alert)
    await db.commit()


# --------------------------------------------------------------------------- notifications


async def list_notifications(
    db: AsyncSession, user_id: uuid.UUID, *, unread_only: bool, limit: int
) -> tuple[list[NotificationOut], int, int]:
    base = select(Notification).where(Notification.user_id == user_id)
    if unread_only:
        base = base.where(Notification.read_at.is_(None))
    rows = list(
        (await db.execute(base.order_by(Notification.created_at.desc()).limit(limit))).scalars()
    )
    unread = (
        await db.scalar(
            select(func.count()).where(
                Notification.user_id == user_id, Notification.read_at.is_(None)
            )
        )
        or 0
    )
    total = await db.scalar(select(func.count()).where(Notification.user_id == user_id)) or 0
    return [
        NotificationOut(
            id=n.id, kind=n.kind, title=n.title, body=n.body, data=n.data,
            alert_id=n.alert_id, created_at=n.created_at, read_at=n.read_at,
        )
        for n in rows
    ], unread, total  # fmt: skip


async def mark_read(db: AsyncSession, user_id: uuid.UUID, notification_id: int | None) -> int:
    stmt = update(Notification).where(
        Notification.user_id == user_id, Notification.read_at.is_(None)
    )
    if notification_id is not None:
        stmt = stmt.where(Notification.id == notification_id)
    result = await db.execute(stmt.values(read_at=utcnow()))
    await db.commit()
    return int(result.rowcount)  # type: ignore[attr-defined]


async def prune_notifications(db: AsyncSession) -> None:
    """Retention: read notifications 90 days, unread 180 days."""
    from sqlalchemy import delete

    now = utcnow()
    await db.execute(
        delete(Notification).where(
            Notification.read_at.is_not(None), Notification.created_at < now - timedelta(days=90)
        )
    )
    await db.execute(
        delete(Notification).where(Notification.created_at < now - timedelta(days=180))
    )
    await db.commit()


# --------------------------------------------------------------------------- evaluation


async def _observations(
    db: AsyncSession, alerts: list[Alert], provider: CandleProvider
) -> dict[uuid.UUID, conditions.Observation]:
    """Build one observation per alert, computing each (asset, timeframe) analysis once."""
    from app.modules.portfolio import service as portfolio
    from app.modules.signals import service as signals

    asset_ids = list({a.cryptocurrency_id for a in alerts if a.cryptocurrency_id})
    cryptos = await market.cryptos_by_id(db, asset_ids)
    tickers = await market.live_tickers(db, asset_ids)
    fx = await market.usd_brl_at(db, utcnow())

    analyses: dict[tuple[uuid.UUID, str], conditions.Observation] = {}
    for crypto_id, timeframe in {
        (a.cryptocurrency_id, a.timeframe)
        for a in alerts
        if a.type in INDICATOR_TYPES
        and a.type != AlertType.SIGNAL_CHANGE
        and a.cryptocurrency_id
        and a.timeframe
    }:
        crypto = cryptos.get(crypto_id)
        if crypto is None:
            continue
        try:
            candle_set = await candle_service.get_candles(db, crypto, timeframe, provider)  # type: ignore[arg-type]
        except (AppError, ProviderError):
            continue
        if candle_set.is_stale:
            continue  # never alert on outdated prices
        result = analyze(candle_set.candles, timeframe)  # type: ignore[arg-type]
        s = result.snapshot
        if s is None:
            continue
        analyses[(crypto_id, timeframe)] = conditions.Observation(
            symbol=crypto.symbol,
            candle_time=s.as_of.isoformat(),
            rsi=s.rsi,
            ema={
                p: v
                for p, v in ((9, s.ema9), (21, s.ema21), (50, s.ema50), (200, s.ema200))
                if v is not None
            },
            volume_ratio=s.volume_ratio,
            trend=result.trend.classification if result.trend else None,
        )

    weights: dict[uuid.UUID, list[tuple[str, uuid.UUID, Decimal]]] = {}
    for user_id in {a.user_id for a in alerts if a.type == AlertType.CONCENTRATION}:
        try:
            summary = await portfolio.summary(
                db, (await portfolio.list_portfolios(db, user_id))[0], "USD"
            )
        except AppError:
            continue
        weights[user_id] = [(p.asset.symbol, p.asset.id, p.weight_pct) for p in summary.positions]

    observations: dict[uuid.UUID, conditions.Observation] = {}
    for a in alerts:
        crypto = cryptos.get(a.cryptocurrency_id) if a.cryptocurrency_id else None
        if a.type in (AlertType.PRICE_ABOVE, AlertType.PRICE_BELOW):
            ticker = tickers.get(a.cryptocurrency_id) if a.cryptocurrency_id else None
            if (
                crypto is None
                or ticker is None
                or market.utcnow() - ticker.fetched_at > timedelta(minutes=30)
            ):
                continue  # missing or stale quote: skip rather than alert on old data
            currency = a.params.get("currency", "USD")
            if currency == "BRL" and fx is None:
                continue
            price = ticker.price * (fx if currency == "BRL" and fx else Decimal(1))
            observations[a.id] = conditions.Observation(
                symbol=crypto.symbol, price=price, currency=currency
            )
        elif a.type == AlertType.SIGNAL_CHANGE and crypto and a.timeframe:
            latest = await signals.latest_classification(db, crypto.id, a.timeframe)
            if latest is not None and not latest.data_is_stale:
                observations[a.id] = conditions.Observation(
                    symbol=crypto.symbol,
                    candle_time=latest.candle_time.isoformat(),
                    signal=latest.classification,
                    signal_score=latest.score,
                )
        elif a.type in INDICATOR_TYPES and a.cryptocurrency_id and a.timeframe:
            obs = analyses.get((a.cryptocurrency_id, a.timeframe))
            if obs is not None:
                observations[a.id] = obs
        elif a.type == AlertType.CONCENTRATION and a.user_id in weights:
            positions = weights[a.user_id]
            if a.cryptocurrency_id:
                match = next((p for p in positions if p[1] == a.cryptocurrency_id), None)
                weight = (
                    (match[0], match[2]) if match else (crypto.symbol if crypto else "", Decimal(0))
                )
            else:
                top = max(positions, key=lambda p: p[2], default=None)
                weight = (top[0], top[2]) if top else ("", Decimal(0))
            observations[a.id] = conditions.Observation(
                weight_symbol=weight[0], weight_pct=weight[1]
            )
    return observations


async def evaluate_all(db: AsyncSession, provider: CandleProvider) -> int:
    """Evaluate every active alert; returns the number of notifications created."""
    alerts = list((await db.execute(select(Alert).where(Alert.is_active.is_(True)))).scalars())
    if not alerts:
        return 0
    observations = await _observations(db, alerts, provider)
    users = {
        u.id: u
        for u in (
            await db.execute(select(User).where(User.id.in_({a.user_id for a in alerts})))
        ).scalars()
    }
    slugs = {
        c.id: c.source_id
        for c in (
            await market.cryptos_by_id(
                db, [a.cryptocurrency_id for a in alerts if a.cryptocurrency_id]
            )
        ).values()
    }
    now = utcnow()
    created = 0
    pending_channels: list[tuple[User, Notification, Alert]] = []
    per_user_created: dict[uuid.UUID, int] = defaultdict(int)

    for alert in alerts:
        obs = observations.get(alert.id)
        if obs is None:
            continue
        state, event = conditions.evaluate(alert.type, alert.params, obs, alert.last_state)
        if state is None:
            continue
        alert.last_state = state
        alert.last_evaluated_at = now
        if event is None:
            continue
        cooling = alert.last_triggered_at and now - alert.last_triggered_at < timedelta(
            minutes=alert.cooldown_minutes
        )
        if cooling:
            continue
        if not (
            await rate_limit.hit(f"notify:inapp:{alert.user_id}", IN_APP_PER_HOUR, 3600)
        ).allowed:
            logger.warning("alert_rate_limited", user_id=str(alert.user_id), alert_id=str(alert.id))
            continue
        window = int(now.timestamp() // (alert.cooldown_minutes * 60))
        inserted = (
            await db.execute(
                insert(Notification)
                .values(
                    user_id=alert.user_id,
                    alert_id=alert.id,
                    kind="alert",
                    title=event.title[:160],
                    body=event.body,
                    data={
                        "asset_slug": slugs.get(alert.cryptocurrency_id)
                        if alert.cryptocurrency_id
                        else None,
                        "value": event.value,
                        "type": alert.type.value,
                    },
                    dedupe_key=f"{alert.id}:{event.key}:{window}"[:160],
                    channels=["in_app"],
                )
                .on_conflict_do_nothing()
                .returning(Notification.id)
            )
        ).scalar_one_or_none()
        if inserted is None:
            continue  # same occurrence already notified
        alert.last_triggered_at = now
        alert.trigger_count += 1
        created += 1
        per_user_created[alert.user_id] += 1
        notification = await db.get(Notification, inserted)
        if notification is not None and alert.user_id in users:
            pending_channels.append((users[alert.user_id], notification, alert))
    await db.commit()

    for user, notification, alert in pending_channels:
        sent = [ch.name for ch in CHANNELS if ch.wants(alert) and await ch.send(user, notification)]
        if sent:
            notification.channels = ["in_app", *sent]
    await db.commit()
    if created:
        logger.info("alerts_triggered", notifications=created, users=len(per_user_created))
    return created
