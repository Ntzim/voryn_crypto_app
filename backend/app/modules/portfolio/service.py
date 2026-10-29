"""Portfolio use-cases: transactions CRUD, valuation, performance and insights.

Every read replays the full transaction history through the engine (see engine.py). A
personal portfolio has at most a few thousand transactions, so this stays in the low
milliseconds while guaranteeing figures always reflect the latest edits.
"""

import contextlib
import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError, NotFoundError
from app.core.tasks import enqueue
from app.modules.audit.service import record
from app.modules.market_data import service as market
from app.modules.market_data.models import Cryptocurrency, MarketTicker
from app.modules.market_data.providers.base import FxHistoryProvider, ProviderError
from app.modules.portfolio import insights as insight_rules
from app.modules.portfolio.engine import (
    ZERO,
    InsufficientBalanceError,
    InvalidEntryError,
    Ledger,
    LedgerEntry,
    replay,
)
from app.modules.portfolio.models import Exchange, Portfolio, Transaction
from app.modules.portfolio.performance import chain, change_24h, daily_series, twr_index, xirr
from app.modules.portfolio.schemas import (
    AssetRef,
    Change24hOut,
    Currency,
    InsightsOut,
    PerformanceOut,
    PortfolioOut,
    PositionOut,
    PriceStatus,
    ReturnsOut,
    SeriesPoint,
    SummaryOut,
    TransactionIn,
    TransactionOut,
)

DEFAULT_PORTFOLIO_NAME = "Minha carteira"
HISTORY_TASK = "portfolio.refresh_history"
BENCHMARKS = ("bitcoin", "ethereum")
MONEY = Decimal("0.00000001")
PCT = Decimal("0.0001")


class InsufficientBalanceApiError(AppError):
    status_code = 422
    code = "insufficient_balance"


class InvalidTransactionError(AppError):
    status_code = 422
    code = "invalid_transaction"


class FxForDateUnavailableError(AppError):
    status_code = 503
    code = "fx_unavailable"
    message = "Não foi possível obter a cotação USD/BRL da data da operação. Tente novamente."


def utcnow() -> datetime:
    return datetime.now(UTC)


def q(value: Decimal | None, step: Decimal = MONEY) -> Decimal | None:
    return None if value is None else value.quantize(step)


def qm(value: Decimal) -> Decimal:
    return value.quantize(MONEY)


# --------------------------------------------------------------------------- portfolios


async def list_portfolios(db: AsyncSession, user_id: uuid.UUID) -> list[Portfolio]:
    portfolios = list(
        (
            await db.execute(
                select(Portfolio).where(Portfolio.user_id == user_id).order_by(Portfolio.created_at)
            )
        ).scalars()
    )
    if not portfolios:
        portfolio = Portfolio(user_id=user_id, name=DEFAULT_PORTFOLIO_NAME)
        db.add(portfolio)
        await db.commit()
        portfolios = [portfolio]
    return portfolios


async def get_portfolio(db: AsyncSession, user_id: uuid.UUID, portfolio_id: uuid.UUID) -> Portfolio:
    portfolio = (
        await db.execute(
            select(Portfolio).where(Portfolio.id == portfolio_id, Portfolio.user_id == user_id)
        )
    ).scalar_one_or_none()
    if portfolio is None:
        raise NotFoundError("Carteira não encontrada.")
    return portfolio


async def list_exchanges(db: AsyncSession) -> list[Exchange]:
    return list((await db.execute(select(Exchange).order_by(Exchange.name))).scalars())


async def transactions(db: AsyncSession, portfolio_id: uuid.UUID) -> list[Transaction]:
    """All transactions in replay order (executed_at, created_at)."""
    return await _transactions(db, portfolio_id)


async def _transactions(db: AsyncSession, portfolio_id: uuid.UUID) -> list[Transaction]:
    return list(
        (
            await db.execute(
                select(Transaction)
                .where(Transaction.portfolio_id == portfolio_id)
                .order_by(Transaction.executed_at, Transaction.created_at, Transaction.id)
            )
        ).scalars()
    )


def _asset_ref(c: Cryptocurrency) -> AssetRef:
    return AssetRef(id=c.id, slug=c.source_id, symbol=c.symbol, name=c.name, image_url=c.image_url)


# --------------------------------------------------------------------------- currency


def to_reporting(amount: Decimal, quote: str, fx_usd_brl: Decimal, reporting: str) -> Decimal:
    if quote == reporting:
        return amount
    if quote == "USD" and reporting == "BRL":
        return amount * fx_usd_brl
    if quote == "BRL" and reporting == "USD":
        return amount / fx_usd_brl
    raise ValueError(f"unsupported conversion {quote}->{reporting}")


def ledger_entries(txs: Sequence[Transaction], reporting: str) -> list[LedgerEntry]:
    entries = []
    for t in txs:

        def conv(amount: Decimal, t: Transaction = t) -> Decimal:
            return to_reporting(amount, t.quote_currency, t.fx_usd_brl, reporting)

        entries.append(
            LedgerEntry(
                id=str(t.id),
                type=t.type,
                executed_at=t.executed_at,
                asset=t.cryptocurrency_id,
                quantity=t.quantity,
                gross=conv(t.gross_amount) if t.gross_amount is not None else None,
                fee=conv(t.fee_amount),
                fee_quantity=t.fee_quantity,
                to_asset=t.to_cryptocurrency_id,
                to_quantity=t.to_quantity,
            )
        )
    return entries


async def resolve_fx(db: AsyncSession, fx_history: FxHistoryProvider, when: datetime) -> Decimal:
    """USD→BRL in force at `when`: stored observation, else fetch official PTAX history."""
    rate = await market.usd_brl_at(db, when)
    if rate is not None:
        return rate
    with contextlib.suppress(ProviderError):
        await market.backfill_fx_history(db, fx_history, (when - timedelta(days=10)).date())
    rate = await market.usd_brl_at(db, when)
    if rate is None and utcnow() - when < timedelta(days=2):
        # Today's PTAX is published around 13h Brasília; use the latest live rate meanwhile.
        rate = await market.usd_brl_at(db, utcnow())
    if rate is None:
        raise FxForDateUnavailableError()
    return rate


# --------------------------------------------------------------------------- transactions


async def _validate_history(db: AsyncSession, txs: Sequence[Transaction]) -> None:
    ordered = sorted(txs, key=lambda t: (t.executed_at, t.created_at or utcnow(), str(t.id)))
    try:
        # Quantities don't depend on currency; any reporting currency validates.
        replay(ledger_entries(ordered, "USD"))
    except InsufficientBalanceError as exc:
        crypto = (await market.cryptos_by_id(db, [exc.asset])).get(exc.asset)
        symbol = crypto.symbol if crypto else "ativo"
        offending = next((t for t in ordered if str(t.id) == exc.entry_id), None)
        when = f" em {offending.executed_at:%d/%m/%Y %H:%M} UTC" if offending else ""
        raise InsufficientBalanceApiError(
            f"Saldo insuficiente de {symbol}{when}: disponível {qm(exc.available).normalize()}, "
            f"necessário {exc.requested.normalize()}. Registre antes as entradas desse ativo.",
            details={"transaction_id": exc.entry_id, "asset_id": str(exc.asset)},
        ) from exc
    except InvalidEntryError as exc:
        raise InvalidTransactionError(f"Transação inválida: {exc.reason}.") from exc


async def _check_references(db: AsyncSession, data: TransactionIn) -> None:
    asset_ids = [data.asset_id] + ([data.to_asset_id] if data.to_asset_id else [])
    found = await market.cryptos_by_id(db, asset_ids)
    if len(found) != len(set(asset_ids)):
        raise InvalidTransactionError("Ativo desconhecido.")
    for exchange_id in filter(None, (data.exchange_id, data.to_exchange_id)):
        if await db.get(Exchange, exchange_id) is None:
            raise InvalidTransactionError("Exchange desconhecida.")


def _apply_fields(tx: Transaction, data: TransactionIn, fx: Decimal) -> None:
    tx.type = data.type
    tx.cryptocurrency_id = data.asset_id
    tx.quantity = data.quantity
    tx.unit_price = data.unit_price
    tx.quote_currency = data.quote_currency
    tx.gross_amount = data.quantity * data.unit_price if data.unit_price is not None else None
    tx.fee_amount = data.fee_amount
    tx.fee_quantity = data.fee_quantity
    tx.to_cryptocurrency_id = data.to_asset_id
    tx.to_quantity = data.to_quantity
    tx.executed_at = data.executed_at
    tx.exchange_id = data.exchange_id
    tx.to_exchange_id = data.to_exchange_id
    tx.notes = data.notes
    tx.fx_usd_brl = fx


async def create_transactions(
    db: AsyncSession,
    fx_history: FxHistoryProvider,
    portfolio: Portfolio,
    items: Sequence[tuple[TransactionIn, str, str | None]],
    *,
    ip: str | None,
) -> list[Transaction]:
    """Insert (data, source, external_id) items atomically after validating the history."""
    created = []
    for data, source, external_id in items:
        await _check_references(db, data)
        tx = Transaction(
            id=uuid.uuid4(),
            portfolio_id=portfolio.id,
            user_id=portfolio.user_id,
            source=source,
            external_id=external_id,
            created_at=utcnow(),
        )
        _apply_fields(tx, data, await resolve_fx(db, fx_history, data.executed_at))
        created.append(tx)
    await _validate_history(db, [*await _transactions(db, portfolio.id), *created])
    db.add_all(created)
    record(
        db,
        "portfolio.transactions_created",
        user_id=portfolio.user_id,
        ip_address=ip,
        portfolio_id=str(portfolio.id),
        count=len(created),
        source=items[0][1] if items else None,
    )
    await db.commit()
    await enqueue(HISTORY_TASK)
    return created


async def _get_transaction(db: AsyncSession, portfolio: Portfolio, tx_id: uuid.UUID) -> Transaction:
    tx = (
        await db.execute(
            select(Transaction).where(
                Transaction.id == tx_id, Transaction.portfolio_id == portfolio.id
            )
        )
    ).scalar_one_or_none()
    if tx is None:
        raise NotFoundError("Transação não encontrada.")
    return tx


async def update_transaction(
    db: AsyncSession,
    fx_history: FxHistoryProvider,
    portfolio: Portfolio,
    tx_id: uuid.UUID,
    data: TransactionIn,
    *,
    ip: str | None,
) -> Transaction:
    tx = await _get_transaction(db, portfolio, tx_id)
    await _check_references(db, data)
    fx = (
        tx.fx_usd_brl
        if tx.executed_at == data.executed_at
        else await resolve_fx(db, fx_history, data.executed_at)
    )
    _apply_fields(tx, data, fx)
    try:
        await _validate_history(db, await _transactions(db, portfolio.id))
    except AppError:
        await db.rollback()
        raise
    record(
        db,
        "portfolio.transaction_updated",
        user_id=portfolio.user_id,
        ip_address=ip,
        transaction_id=str(tx_id),
    )
    await db.commit()
    await enqueue(HISTORY_TASK)
    return tx


async def delete_transaction(
    db: AsyncSession, portfolio: Portfolio, tx_id: uuid.UUID, *, ip: str | None
) -> None:
    tx = await _get_transaction(db, portfolio, tx_id)
    remaining = [t for t in await _transactions(db, portfolio.id) if t.id != tx.id]
    # Deleting a purchase can make a later sale impossible; refuse instead of corrupting.
    await _validate_history(db, remaining)
    await db.delete(tx)
    record(
        db,
        "portfolio.transaction_deleted",
        user_id=portfolio.user_id,
        ip_address=ip,
        transaction_id=str(tx_id),
    )
    await db.commit()
    await enqueue(HISTORY_TASK)


async def list_transactions(
    db: AsyncSession,
    portfolio: Portfolio,
    *,
    type_: str | None,
    asset_id: uuid.UUID | None,
    page: int,
    page_size: int,
) -> tuple[list[TransactionOut], int]:
    query = select(Transaction).where(Transaction.portfolio_id == portfolio.id)
    if type_:
        query = query.where(Transaction.type == type_)
    if asset_id:
        query = query.where(
            (Transaction.cryptocurrency_id == asset_id)
            | (Transaction.to_cryptocurrency_id == asset_id)
        )
    total = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    txs = list(
        (
            await db.execute(
                query.order_by(Transaction.executed_at.desc(), Transaction.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars()
    )
    return await transactions_out(db, txs), total


async def transactions_out(db: AsyncSession, txs: Sequence[Transaction]) -> list[TransactionOut]:
    ids = {t.cryptocurrency_id for t in txs} | {
        t.to_cryptocurrency_id for t in txs if t.to_cryptocurrency_id
    }
    cryptos = await market.cryptos_by_id(db, list(ids))
    return [
        TransactionOut(
            id=t.id,
            type=t.type,
            asset=_asset_ref(cryptos[t.cryptocurrency_id]),
            quantity=t.quantity,
            unit_price=t.unit_price,
            quote_currency=t.quote_currency,
            gross_amount=t.gross_amount,
            fee_amount=t.fee_amount,
            fee_quantity=t.fee_quantity,
            to_asset=_asset_ref(cryptos[t.to_cryptocurrency_id])
            if t.to_cryptocurrency_id
            else None,
            to_quantity=t.to_quantity,
            fx_usd_brl=t.fx_usd_brl,
            executed_at=t.executed_at,
            exchange_id=t.exchange_id,
            to_exchange_id=t.to_exchange_id,
            notes=t.notes,
            source=t.source,
            created_at=t.created_at,
        )
        for t in txs
    ]


# --------------------------------------------------------------------------- valuation


class _Valuation:
    """Live valuation context shared by summary, performance and insights."""

    def __init__(
        self,
        txs: list[Transaction],
        entries: list[LedgerEntry],
        ledger: Ledger,
        cryptos: dict[uuid.UUID, Cryptocurrency],
        tickers: dict[uuid.UUID, MarketTicker],
        fx_now: Decimal | None,
        currency: Currency,
    ) -> None:
        self.txs, self.entries, self.ledger = txs, entries, ledger
        self.cryptos, self.tickers, self.fx_now, self.currency = cryptos, tickers, fx_now, currency

    def usd_to_reporting(self) -> Decimal:
        if self.currency == "USD":
            return Decimal(1)
        assert self.fx_now is not None
        return self.fx_now

    def price(self, asset: uuid.UUID) -> Decimal | None:
        ticker = self.tickers.get(asset)
        return ticker.price * self.usd_to_reporting() if ticker else None

    def value_of(self, asset: uuid.UUID, quantity: Decimal) -> tuple[Decimal, bool]:
        price = self.price(asset)
        if price is not None:
            return quantity * price, False
        return quantity * self.ledger.last_price.get(asset, ZERO), True

    def market_value(self) -> Decimal:
        return sum((self.value_of(a, qty)[0] for a, qty in self.ledger.quantities().items()), ZERO)


async def _valuation(db: AsyncSession, portfolio: Portfolio, currency: Currency) -> _Valuation:
    txs = await _transactions(db, portfolio.id)
    entries = ledger_entries(txs, currency)
    ledger = replay(entries)
    asset_ids = list(ledger.positions)
    fx_now = await market.usd_brl_at(db, utcnow())
    if currency == "BRL" and fx_now is None:
        raise market.FxUnavailableError()
    return _Valuation(
        txs,
        entries,
        ledger,
        await market.cryptos_by_id(db, asset_ids),
        await market.live_tickers(db, asset_ids),
        fx_now,
        currency,
    )


async def summary(db: AsyncSession, portfolio: Portfolio, currency: Currency) -> SummaryOut:
    v = await _valuation(db, portfolio, currency)
    now = utcnow()
    total_value = v.market_value()

    positions: list[PositionOut] = []
    closed: list[PositionOut] = []
    for asset, pos in v.ledger.positions.items():
        value, estimated = v.value_of(asset, pos.quantity)
        unrealized = value - pos.cost_basis if pos.quantity > 0 else ZERO
        ticker = v.tickers.get(asset)
        out = PositionOut(
            asset=_asset_ref(v.cryptos[asset]),
            quantity=pos.quantity,
            price=q(v.price(asset)),
            market_value=qm(value),
            cost_basis=qm(pos.cost_basis),
            average_cost=q(pos.average_cost),
            unrealized_pnl=qm(unrealized),
            unrealized_pct=q(unrealized / pos.cost_basis * 100, PCT)
            if pos.cost_basis > 0
            else None,
            realized_pnl=qm(pos.realized_pnl),
            fees=qm(pos.fees),
            change_pct_24h=ticker.change_pct_24h if ticker else None,
            weight_pct=(value / total_value * 100).quantize(PCT) if total_value > 0 else Decimal(0),
            price_estimated=estimated,
        )
        (positions if pos.quantity > 0 else closed).append(out)
    positions.sort(key=lambda p: p.market_value, reverse=True)

    # 24h: holdings a day ago × prices a day ago (derived from the provider's 24h change).
    since = now - timedelta(hours=24)
    then = replay([e for e in v.entries if e.executed_at <= since])
    fx_then = (await market.usd_brl_at(db, since)) or v.fx_now if currency == "BRL" else Decimal(1)
    value_then = ZERO
    for asset, qty in then.quantities().items():
        ticker = v.tickers.get(asset)
        if ticker is None:
            value_then += qty * then.last_price.get(asset, ZERO)
            continue
        pct = ticker.change_pct_24h or ZERO
        value_then += qty * ticker.price / (1 + pct / 100) * (fx_then or Decimal(1))
    change = change_24h(value_then, total_value, v.ledger.flows, since)

    inflows = sum((f.amount for f in v.ledger.flows if f.amount > 0), ZERO)
    outflows = -sum((f.amount for f in v.ledger.flows if f.amount < 0), ZERO)
    cost = sum((p.cost_basis for p in v.ledger.positions.values()), ZERO)
    realized = sum((p.realized_pnl for p in v.ledger.positions.values()), ZERO)
    fetched = [t.fetched_at for t in v.tickers.values()]
    oldest = min(fetched) if fetched else None
    total_usd = total_value if currency == "USD" else total_value / v.fx_now  # type: ignore[operator]
    return SummaryOut(
        portfolio=PortfolioOut.model_validate(portfolio),
        currency=currency,
        market_value=qm(total_value),
        market_value_usd=qm(total_usd),
        market_value_brl=qm(total_usd * v.fx_now) if v.fx_now else qm(ZERO),
        cost_basis=qm(cost),
        unrealized_pnl=qm(total_value - cost),
        realized_pnl=qm(realized),
        total_pnl=qm(total_value - cost + realized),
        total_inflows=qm(inflows),
        total_outflows=qm(outflows),
        net_invested=qm(inflows - outflows),
        fees=qm(sum((p.fees for p in v.ledger.positions.values()), ZERO)),
        change_24h=Change24hOut(
            value_change=qm(change.value_now - change.value_then),
            market_effect=qm(change.market_effect),
            net_flows=qm(change.net_flows),
            pct=q(change.pct, PCT),
        ),
        positions=positions,
        closed_positions=closed,
        transaction_count=len(v.txs),
        fx_usd_brl=v.fx_now,
        prices=PriceStatus(
            fetched_at=oldest,
            is_stale=oldest is not None
            and now - oldest > timedelta(seconds=get_settings().market_stale_after_seconds),
            missing_assets=[
                v.cryptos[a].symbol for a in v.ledger.quantities() if a not in v.tickers
            ],
        ),
        as_of=now,
    )


async def performance(db: AsyncSession, portfolio: Portfolio, currency: Currency) -> PerformanceOut:
    v = await _valuation(db, portfolio, currency)
    now = utcnow()
    today = now.date()
    empty_returns = ReturnsOut(d1=None, d7=None, d30=None, d90=None, y1=None, inception=None)
    if not v.entries:
        return PerformanceOut(
            currency=currency,
            inception_date=None,
            history_start=None,
            history_complete=True,
            series=[],
            returns=empty_returns,
            xirr_pct=None,
            xirr_applicable=False,
            as_of=now,
        )

    inception = v.entries[0].executed_at.date()
    yesterday = today - timedelta(days=1)
    start = max(inception, today - timedelta(days=365))
    truncated = start > inception

    benchmark_ids = {c.source_id: c.id for c in (await _cryptos_by_slug(db, BENCHMARKS))}
    asset_ids = list(set(v.ledger.positions) | set(benchmark_ids.values()))
    closes = await market.daily_closes(db, asset_ids, start, yesterday)
    fx_daily = await market.usd_brl_daily(db, start, yesterday) if currency == "BRL" else None

    def fx_lookup(day: date) -> Decimal | None:
        return fx_daily.get(day) if fx_daily is not None else Decimal(1)

    points, _ = (
        daily_series(v.entries, start, yesterday, closes, fx_lookup)
        if start <= yesterday
        else ([], Ledger())
    )
    index = twr_index(points, opening_value=None if truncated else ZERO)

    today_start = datetime.combine(today, time(), UTC)
    flow_today = sum((f.amount for f in v.ledger.flows if f.at >= today_start), ZERO)
    value_now = v.market_value()
    if points:
        level_now = chain(index[-1], points[-1].value, flow_today, value_now)
    else:
        level_now = value_now / flow_today if flow_today > 0 else Decimal(1)

    by_day = {p.day: (p, lvl) for p, lvl in zip(points, index, strict=True)}

    def period(days: int) -> Decimal | None:
        anchor = by_day.get(today - timedelta(days=days))
        if anchor is None:
            return None
        return ((level_now / anchor[1] - 1) * 100).quantize(PCT)

    summary_out = await summary(db, portfolio, currency)

    def bench(slug: str) -> list[Decimal | None]:
        crypto_id = benchmark_ids.get(slug)
        series = closes.get(crypto_id, {}) if crypto_id else {}
        base = next((series[p.day] for p in points if p.day in series), None)
        return [
            ((series[p.day] / base - 1) * 100).quantize(PCT) if base and p.day in series else None
            for p in points
        ]

    btc, eth = bench("bitcoin"), bench("ethereum")
    series_out = [
        SeriesPoint(
            day=p.day,
            value=qm(p.value),
            net_invested=qm(p.net_invested),
            flow=qm(p.flow),
            twr_pct=((lvl - 1) * 100).quantize(PCT),
            btc_pct=b,
            eth_pct=e,
            estimated=p.estimated,
        )
        for p, lvl, b, e in zip(points, index, btc, eth, strict=True)
    ]

    cash_flows = [(f.at, -f.amount) for f in v.ledger.flows] + [(now, value_now)]
    rate = xirr(cash_flows)
    applicable = (today - inception).days >= 30
    return PerformanceOut(
        currency=currency,
        inception_date=inception,
        history_start=start,
        history_complete=not truncated and not any(p.estimated for p in points),
        series=series_out,
        returns=ReturnsOut(
            d1=summary_out.change_24h.pct,
            d7=period(7),
            d30=period(30),
            d90=period(90),
            y1=period(365),
            inception=None if truncated else ((level_now - 1) * 100).quantize(PCT),
        ),
        xirr_pct=(rate * 100).quantize(PCT) if rate is not None and applicable else None,
        xirr_applicable=applicable,
        as_of=now,
    )


async def _cryptos_by_slug(db: AsyncSession, slugs: Sequence[str]) -> list[Cryptocurrency]:
    return list(
        (
            await db.execute(
                select(Cryptocurrency).where(Cryptocurrency.source_id.in_(list(slugs)))
            )
        ).scalars()
    )


async def insights(db: AsyncSession, portfolio: Portfolio, currency: Currency) -> InsightsOut:
    summary_out = await summary(db, portfolio, currency)
    top = summary_out.positions[:2]
    returns: dict[str, list[Decimal]] = {}
    if len(top) == 2:
        today = utcnow().date()
        closes = await market.daily_closes(
            db, [p.asset.id for p in top], today - timedelta(days=91), today - timedelta(days=1)
        )
        returns = insight_rules.aligned_returns(
            {p.asset.symbol: closes.get(p.asset.id, {}) for p in top}
        )
    return InsightsOut(items=insight_rules.build(summary_out, returns), as_of=summary_out.as_of)


# --------------------------------------------------------------------------- jobs


async def held_assets(db: AsyncSession) -> dict[uuid.UUID, str]:
    """Every asset referenced by any transaction (for price sync and history backfill)."""
    ids = set((await db.execute(select(Transaction.cryptocurrency_id).distinct())).scalars())
    ids |= {
        i
        for i in (await db.execute(select(Transaction.to_cryptocurrency_id).distinct())).scalars()
        if i is not None
    }
    cryptos = await market.cryptos_by_id(db, list(ids))
    return {c.id: c.source_id for c in cryptos.values()}


async def earliest_transaction_date(db: AsyncSession) -> date | None:
    first = await db.scalar(select(func.min(Transaction.executed_at)))
    return first.date() if first else None
