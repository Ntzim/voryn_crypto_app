"""Exchange connections: validate read-only keys, sync, import and reconcile."""

import uuid
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import rate_limit, security_events
from app.core.authz import owned_or_404
from app.core.crypto import decrypt, encrypt
from app.core.errors import AppError
from app.core.logging import get_logger
from app.core.security import hash_token
from app.core.tasks import enqueue
from app.modules.audit.service import AuditAction
from app.modules.audit.service import record as audit
from app.modules.exchange_connections import mapping
from app.modules.exchange_connections.connectors.base import (
    ConnectorAuthError,
    ConnectorError,
    ExchangeConnector,
)
from app.modules.exchange_connections.connectors.binance import BinanceConnector
from app.modules.exchange_connections.models import ExchangeConnection, ExchangeRecord
from app.modules.exchange_connections.schemas import (
    ConnectionIn,
    ConnectionOut,
    ReconciliationOut,
    RecordOut,
)
from app.modules.market_data import candles as candle_service
from app.modules.market_data import service as market
from app.modules.market_data.models import Cryptocurrency
from app.modules.market_data.providers.base import CandleProvider, FxHistoryProvider
from app.modules.portfolio import service as portfolio
from app.modules.portfolio.engine import TxType
from app.modules.portfolio.models import Portfolio, Transaction

logger = get_logger(__name__)

SYNC_TASK = "exchanges.sync"
SUPPORTED = {"binance": "Binance"}
CONNECTIONS_PER_HOUR = 5
SYNC_COOLDOWN = timedelta(minutes=2)
#: relative tolerance for balance reconciliation (exchange rounding of dust)
TOLERANCE = Decimal("0.000001")

ConnectorFactory = Callable[[str, str, str], ExchangeConnector]


class ConnectionRejectedError(AppError):
    status_code = 422
    code = "exchange_key_rejected"


def connector_for(exchange_id: str, api_key: str, api_secret: str) -> ExchangeConnector:
    if exchange_id == "binance":
        return BinanceConnector(api_key, api_secret)
    raise ConnectionRejectedError("Corretora não suportada.")


def utcnow() -> datetime:
    return datetime.now(UTC)


# --------------------------------------------------------------------------- CRUD


async def create_connection(
    db: AsyncSession,
    user_id: uuid.UUID,
    portfolio_row: Portfolio,
    body: ConnectionIn,
    factory: ConnectorFactory,
    ip: str | None,
) -> ExchangeConnection:
    await rate_limit.enforce(f"exchanges:connect:{user_id}", CONNECTIONS_PER_HOUR, 3600)
    api_key, api_secret = body.api_key.get_secret_value(), body.api_secret.get_secret_value()
    fingerprint = hash_token(f"{body.exchange_id}:{api_key}")
    exists = await db.scalar(
        select(ExchangeConnection.id).where(
            ExchangeConnection.user_id == user_id,
            ExchangeConnection.exchange_id == body.exchange_id,
            ExchangeConnection.key_fingerprint == fingerprint,
        )
    )
    if exists:
        raise AppError("Esta chave já está conectada.", code="exchange_duplicate", status_code=409)

    connector = factory(body.exchange_id, api_key, api_secret)
    try:
        perms = await connector.permissions()
    except ConnectorAuthError as exc:
        raise ConnectionRejectedError(exc.message) from None
    except ConnectorError as exc:
        raise AppError(exc.message, code="exchange_unavailable", status_code=503) from None
    finally:
        await connector.aclose()
    if not perms.can_read:
        raise ConnectionRejectedError("A chave não tem permissão de leitura.")
    if not perms.read_only:
        raise ConnectionRejectedError(
            "Por segurança, aceitamos apenas chaves somente leitura. Desative na corretora: "
            + ", ".join(perms.write_permissions)
            + ".",
            details={"write_permissions": perms.write_permissions},
        )

    conn = ExchangeConnection(
        user_id=user_id,
        portfolio_id=portfolio_row.id,
        exchange_id=body.exchange_id,
        label=body.label,
        api_key_encrypted=encrypt(api_key),
        api_secret_encrypted=encrypt(api_secret),
        key_fingerprint=fingerprint,
        key_hint=api_key[-4:],
        permissions={"can_read": perms.can_read, "write_permissions": perms.write_permissions},
        sync_requested_at=utcnow(),
    )
    db.add(conn)
    await db.flush()
    audit(
        db,
        AuditAction.EXCHANGE_CONNECTED,
        user_id=user_id,
        ip_address=ip,
        connection_id=str(conn.id),
        exchange=body.exchange_id,
    )
    await db.commit()
    await enqueue(SYNC_TASK, str(conn.id))
    return conn


async def list_connections(db: AsyncSession, user_id: uuid.UUID) -> list[ExchangeConnection]:
    rows = await db.execute(
        select(ExchangeConnection)
        .where(ExchangeConnection.user_id == user_id)
        .order_by(ExchangeConnection.created_at)
    )
    return list(rows.scalars())


async def get_owned(
    db: AsyncSession, user_id: uuid.UUID, connection_id: uuid.UUID
) -> ExchangeConnection:
    return await owned_or_404(
        db, ExchangeConnection, connection_id, user_id, "Conexão não encontrada."
    )


async def delete_connection(db: AsyncSession, conn: ExchangeConnection, ip: str | None) -> None:
    """Remove credentials and synced records; imported transactions stay in the portfolio."""
    audit(
        db,
        AuditAction.EXCHANGE_DISCONNECTED,
        user_id=conn.user_id,
        ip_address=ip,
        connection_id=str(conn.id),
        exchange=conn.exchange_id,
    )
    await db.delete(conn)
    await db.commit()


async def request_sync(db: AsyncSession, conn: ExchangeConnection) -> None:
    now = utcnow()
    if conn.sync_requested_at and now - conn.sync_requested_at < SYNC_COOLDOWN:
        raise AppError(
            "Uma sincronização foi pedida há pouco. Aguarde alguns minutos.",
            code="sync_throttled",
            status_code=429,
        )
    conn.sync_requested_at = now
    await db.commit()
    await enqueue(SYNC_TASK, str(conn.id))


async def out(db: AsyncSession, conn: ExchangeConnection) -> ConnectionOut:
    rows = await db.execute(
        select(ExchangeRecord.status, func.count())
        .where(ExchangeRecord.connection_id == conn.id)
        .group_by(ExchangeRecord.status)
    )
    counts: dict[str, int] = {status: n for status, n in rows.all()}
    return ConnectionOut(
        id=conn.id,
        exchange_id=conn.exchange_id,
        exchange_name=SUPPORTED.get(conn.exchange_id, conn.exchange_id),
        label=conn.label,
        key_hint=conn.key_hint,
        status=conn.status,
        write_permissions=conn.permissions.get("write_permissions", []),
        last_synced_at=conn.last_synced_at,
        last_error=conn.last_error,
        created_at=conn.created_at,
        imported=counts.get("imported", 0),
        needs_review=counts.get("needs_review", 0),
        pending=counts.get("pending", 0),
        reconciliation=ReconciliationOut.model_validate(conn.reconciliation)
        if conn.reconciliation
        else None,
    )


async def review_records(db: AsyncSession, conn: ExchangeConnection) -> list[RecordOut]:
    rows = await db.execute(
        select(ExchangeRecord)
        .where(ExchangeRecord.connection_id == conn.id, ExchangeRecord.status != "imported")
        .order_by(ExchangeRecord.occurred_at)
        .limit(200)
    )
    return [
        RecordOut(
            id=r.id,
            kind=r.kind,
            external_id=r.external_id,
            occurred_at=r.occurred_at,
            status=r.status,
            reason=r.reason,
            summary=mapping.describe(r),
        )
        for r in rows.scalars()
    ]


# --------------------------------------------------------------------------- sync


def resolver(db: AsyncSession, candles: CandleProvider) -> mapping.Resolver:
    assets: dict[str, Cryptocurrency | None] = {}
    closes: dict[uuid.UUID, dict[date, Decimal]] = {}

    async def asset(symbol: str) -> Cryptocurrency | None:
        if symbol not in assets:
            assets[symbol] = await market.resolve_asset(db, symbol)
        return assets[symbol]

    async def usd_close(crypto: Cryptocurrency, day: date) -> Decimal | None:
        if crypto.id not in closes:
            try:
                got = await candle_service.get_candles(db, crypto, "1d", candles, 1000)
                closes[crypto.id] = {c.open_time.date(): c.close for c in got.candles if c.closed}
            except AppError:
                closes[crypto.id] = {}
        return closes[crypto.id].get(day)

    return mapping.Resolver(asset, usd_close)


async def _sync_failed(
    db: AsyncSession, conn: ExchangeConnection, action: str, reason: str
) -> None:
    """Persist the failure on this connection only; other connections sync independently.

    The stored and audited message is the connector's user-facing text, never the raw
    exchange response or the credentials.
    """
    audit(db, action, user_id=conn.user_id, connection_id=str(conn.id), reason=reason)
    await db.commit()
    await security_events.emit(
        "exchange_sync_failed", connection_id=str(conn.id), exchange=conn.exchange_id, reason=reason
    )


async def sync(
    db: AsyncSession,
    connection_id: uuid.UUID,
    factory: ConnectorFactory,
    candles: CandleProvider,
    fx_history: FxHistoryProvider,
) -> None:
    conn = await db.get(ExchangeConnection, connection_id)
    if conn is None or conn.status == "blocked":
        return
    connector = factory(
        conn.exchange_id, decrypt(conn.api_key_encrypted), decrypt(conn.api_secret_encrypted)
    )
    try:
        perms = await connector.permissions()
        if not perms.read_only:
            conn.status = "blocked"
            conn.last_error = (
                "A chave deixou de ser somente leitura ("
                + ", ".join(perms.write_permissions)
                + "). A sincronização foi suspensa; gere uma nova chave somente leitura."
            )
            conn.permissions = {
                "can_read": perms.can_read,
                "write_permissions": perms.write_permissions,
            }
            await _sync_failed(db, conn, AuditAction.EXCHANGE_BLOCKED, "write_permissions")
            return
        balances = await connector.balances()
        known = set(conn.sync_cursor.get("assets", [])) | set(balances)
        batch = await connector.history(conn.sync_cursor, sorted(known))
    except ConnectorAuthError as exc:
        conn.status, conn.last_error = "blocked", exc.message
        await _sync_failed(db, conn, AuditAction.EXCHANGE_BLOCKED, "key_rejected")
        return
    except ConnectorError as exc:
        conn.status, conn.last_error = "error", exc.message
        await _sync_failed(db, conn, AuditAction.EXCHANGE_SYNC_FAILED, "exchange_error")
        return
    finally:
        await connector.aclose()

    if batch.records:
        await db.execute(
            insert(ExchangeRecord)
            .values(
                [
                    {
                        "connection_id": conn.id,
                        "kind": r.kind,
                        "external_id": r.external_id,
                        "occurred_at": r.occurred_at,
                        "data": r.data,
                    }
                    for r in batch.records
                ]
            )
            .on_conflict_do_nothing(index_elements=["connection_id", "external_id"])
        )
    seen = {str(r.data.get("base") or r.data.get("coin")) for r in batch.records}
    conn.sync_cursor = {**batch.cursor, "assets": sorted(known | seen)}
    await db.commit()

    portfolio_row = await db.get(Portfolio, conn.portfolio_id)
    assert portfolio_row is not None
    await import_records(db, conn, portfolio_row, resolver(db, candles), fx_history)
    conn.reconciliation = (await reconcile(db, conn, balances)).model_dump(mode="json")
    conn.status, conn.last_error, conn.last_synced_at = "active", None, utcnow()
    await db.commit()


async def import_records(
    db: AsyncSession,
    conn: ExchangeConnection,
    portfolio_row: Portfolio,
    resolve: mapping.Resolver,
    fx_history: FxHistoryProvider,
) -> None:
    """Import every record not imported yet, oldest first.

    The whole set is tried at once; if the history does not validate (e.g. a sale of
    coins whose purchase happened outside the synced data), records are imported one by
    one and those that fail stay "needs_review" with the reason.
    """
    records = list(
        (
            await db.execute(
                select(ExchangeRecord)
                .where(ExchangeRecord.connection_id == conn.id, ExchangeRecord.status != "imported")
                .order_by(ExchangeRecord.occurred_at, ExchangeRecord.id)
            )
        ).scalars()
    )
    already = set(
        (
            await db.execute(
                select(Transaction.external_id).where(
                    Transaction.portfolio_id == portfolio_row.id,
                    Transaction.source == conn.exchange_id,
                )
            )
        ).scalars()
    )
    mapped: list[tuple[ExchangeRecord, mapping.Mapped]] = []
    for r in records:
        try:
            items = [
                i
                for i in await mapping.to_transactions(r, conn.exchange_id, resolve)
                if i[1] not in already
            ]
        except mapping.NeedsReviewError as exc:
            r.status, r.reason = "needs_review", exc.reason
            continue
        except ValueError as exc:  # TransactionIn validation
            r.status, r.reason = "needs_review", f"Registro inválido: {exc}"
            continue
        mapped.append((r, items))
    await db.commit()
    if not mapped:
        return

    async def create(items: mapping.Mapped) -> None:
        if items:
            await portfolio.create_transactions(
                db,
                fx_history,
                portfolio_row,
                [(data, conn.exchange_id, ext) for data, ext in items],
                ip=None,
            )

    # create_transactions validates the whole history before adding anything to the
    # session, so a rejected attempt leaves nothing to roll back.
    try:
        await create([i for _, items in mapped for i in items])
    except AppError:
        pass
    else:
        for r, _ in mapped:
            r.status, r.reason = "imported", None
        await db.commit()
        return

    for r, items in mapped:
        try:
            await create(items)
        except AppError as exc:
            r.status, r.reason = "needs_review", exc.message
        else:
            r.status, r.reason = "imported", None
        await db.commit()


async def reconcile(
    db: AsyncSession, conn: ExchangeConnection, balances: dict[str, Decimal]
) -> ReconciliationOut:
    """Compare the exchange's balances with the quantities Voryn attributes to it."""
    txs = await portfolio.transactions(db, conn.portfolio_id)
    held: dict[uuid.UUID, Decimal] = defaultdict(Decimal)
    here = conn.exchange_id
    for t in txs:
        q = t.quantity
        if t.type == TxType.TRANSFER:
            if t.exchange_id == here:
                held[t.cryptocurrency_id] -= q + t.fee_quantity
            if t.to_exchange_id == here:
                held[t.cryptocurrency_id] += q
            continue
        if t.exchange_id != here:
            continue
        if t.type in (TxType.BUY, TxType.DEPOSIT):
            held[t.cryptocurrency_id] += q - t.fee_quantity
        elif t.type in (TxType.SELL, TxType.WITHDRAWAL, TxType.FEE):
            held[t.cryptocurrency_id] -= q + t.fee_quantity
        elif t.type == TxType.CONVERSION and t.to_cryptocurrency_id and t.to_quantity:
            held[t.cryptocurrency_id] -= q + t.fee_quantity
            held[t.to_cryptocurrency_id] += t.to_quantity
    cryptos = await market.cryptos_by_id(db, list(held))
    by_symbol: dict[str, tuple[uuid.UUID | None, Decimal]] = {}
    for crypto_id, qty in held.items():
        symbol = cryptos[crypto_id].symbol.upper() if crypto_id in cryptos else "?"
        prev = by_symbol.get(symbol, (crypto_id, Decimal(0)))
        by_symbol[symbol] = (crypto_id, prev[1] + qty)
    rows: list[dict[str, Any]] = []
    for symbol in sorted(set(balances) | {s for s, (_, q) in by_symbol.items() if q != 0}):
        exchange_qty = balances.get(symbol, Decimal(0))
        asset_id, voryn_qty = by_symbol.get(symbol, (None, Decimal(0)))
        diff = exchange_qty - voryn_qty
        ok = abs(diff) <= max(Decimal("0.00000001"), abs(exchange_qty) * TOLERANCE)
        rows.append(
            {
                "symbol": symbol,
                "asset_id": asset_id,
                "exchange": exchange_qty,
                "voryn": voryn_qty,
                "difference": diff,
                "status": "ok" if ok else "divergent",
            }
        )
    return ReconciliationOut.model_validate(
        {"as_of": utcnow(), "assets": rows, "ok": all(r["status"] == "ok" for r in rows)}
    )


async def due_connections(db: AsyncSession) -> list[uuid.UUID]:
    return list(
        (
            await db.execute(
                select(ExchangeConnection.id).where(ExchangeConnection.status != "blocked")
            )
        ).scalars()
    )
