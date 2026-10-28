import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.core.errors import AppError
from app.modules.auth.deps import CurrentAuth, DbSession, Meta
from app.modules.market_data.providers.base import FxHistoryProvider
from app.modules.market_data.providers.bcb import BcbPtaxProvider
from app.modules.portfolio import csv_import, service
from app.modules.portfolio.engine import TxType
from app.modules.portfolio.models import Portfolio
from app.modules.portfolio.schemas import (
    CsvCommitOut,
    CsvIn,
    CsvPreviewOut,
    CsvRowOut,
    Currency,
    ExchangeOut,
    InsightsOut,
    PerformanceOut,
    PortfolioOut,
    SummaryOut,
    TransactionIn,
    TransactionListOut,
    TransactionOut,
)

router = APIRouter(prefix="/portfolios", tags=["portfolio"])
exchanges_router = APIRouter(prefix="/exchanges", tags=["portfolio"])


async def get_fx_history() -> AsyncIterator[FxHistoryProvider]:
    provider = BcbPtaxProvider()
    try:
        yield provider
    finally:
        await provider.aclose()


FxHistory = Annotated[FxHistoryProvider, Depends(get_fx_history)]


async def owned_portfolio(portfolio_id: uuid.UUID, auth: CurrentAuth, db: DbSession) -> Portfolio:
    return await service.get_portfolio(db, auth.user.id, portfolio_id)


OwnedPortfolio = Annotated[Portfolio, Depends(owned_portfolio)]


def _currency(auth: CurrentAuth, currency: Currency | None = None) -> Currency:
    return currency or auth.user.settings.base_currency  # type: ignore[return-value]


ReportingCurrency = Annotated[Currency, Depends(_currency)]


@exchanges_router.get("")
async def list_exchanges(_: CurrentAuth, db: DbSession) -> list[ExchangeOut]:
    return [ExchangeOut.model_validate(e) for e in await service.list_exchanges(db)]


@router.get("")
async def list_portfolios(auth: CurrentAuth, db: DbSession) -> list[PortfolioOut]:
    """The user's portfolios; a default one is created on first access."""
    return [PortfolioOut.model_validate(p) for p in await service.list_portfolios(db, auth.user.id)]


@router.get("/csv-template", response_class=Response)
async def csv_template(_: CurrentAuth) -> Response:
    return Response(
        csv_import.TEMPLATE,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="voryn-modelo-importacao.csv"'},
    )


@router.get("/{portfolio_id}/summary")
async def summary(
    portfolio: OwnedPortfolio, db: DbSession, currency: ReportingCurrency
) -> SummaryOut:
    return await service.summary(db, portfolio, currency)


@router.get("/{portfolio_id}/performance")
async def performance(
    portfolio: OwnedPortfolio, db: DbSession, currency: ReportingCurrency
) -> PerformanceOut:
    return await service.performance(db, portfolio, currency)


@router.get("/{portfolio_id}/insights")
async def insights(
    portfolio: OwnedPortfolio, db: DbSession, currency: ReportingCurrency
) -> InsightsOut:
    return await service.insights(db, portfolio, currency)


@router.get("/{portfolio_id}/transactions")
async def list_transactions(
    portfolio: OwnedPortfolio,
    db: DbSession,
    type: TxType | None = None,
    asset_id: uuid.UUID | None = None,
    page: Annotated[int, Query(ge=1, le=10_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> TransactionListOut:
    items, total = await service.list_transactions(
        db, portfolio, type_=type, asset_id=asset_id, page=page, page_size=page_size
    )
    return TransactionListOut(items=items, total=total, page=page, page_size=page_size)


@router.post("/{portfolio_id}/transactions", status_code=status.HTTP_201_CREATED)
async def create_transaction(
    data: TransactionIn, portfolio: OwnedPortfolio, db: DbSession, fx: FxHistory, meta: Meta
) -> TransactionOut:
    [tx] = await service.create_transactions(
        db, fx, portfolio, [(data, "manual", None)], ip=meta.ip
    )
    return (await service.transactions_out(db, [tx]))[0]


@router.put("/{portfolio_id}/transactions/{tx_id}")
async def update_transaction(
    tx_id: uuid.UUID,
    data: TransactionIn,
    portfolio: OwnedPortfolio,
    db: DbSession,
    fx: FxHistory,
    meta: Meta,
) -> TransactionOut:
    tx = await service.update_transaction(db, fx, portfolio, tx_id, data, ip=meta.ip)
    return (await service.transactions_out(db, [tx]))[0]


@router.delete("/{portfolio_id}/transactions/{tx_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_transaction(
    tx_id: uuid.UUID, portfolio: OwnedPortfolio, db: DbSession, meta: Meta
) -> None:
    await service.delete_transaction(db, portfolio, tx_id, ip=meta.ip)


def _row_out(row: csv_import.ParsedRow) -> CsvRowOut:
    status_ = "error" if row.errors else "duplicate" if row.duplicate else "valid"
    return CsvRowOut(
        line=row.line,
        status=status_,
        errors=row.errors,
        type=row.raw.get("tipo"),
        asset=row.raw.get("ativo"),
        quantity=row.raw.get("quantidade"),
        unit_price=row.raw.get("preco_unitario"),
        quote_currency=(row.raw.get("moeda") or "BRL").upper(),
        executed_at=row.data.executed_at if row.data else None,
    )


async def _parse(
    db: DbSession, auth: CurrentAuth, portfolio: Portfolio, body: CsvIn
) -> list[csv_import.ParsedRow]:
    rows, file_errors = await csv_import.parse(
        db, portfolio.id, body.content, auth.user.settings.timezone
    )
    if file_errors:
        raise AppError(" ".join(file_errors), code="invalid_csv", status_code=422)
    if not rows:
        raise AppError("O arquivo não contém linhas de dados.", code="invalid_csv", status_code=422)
    return rows


@router.post("/{portfolio_id}/imports/preview")
async def import_preview(
    body: CsvIn, auth: CurrentAuth, portfolio: OwnedPortfolio, db: DbSession
) -> CsvPreviewOut:
    rows = await _parse(db, auth, portfolio, body)
    out = [_row_out(r) for r in rows]
    return CsvPreviewOut(
        rows=out,
        valid=sum(r.status == "valid" for r in out),
        errors=sum(r.status == "error" for r in out),
        duplicates=sum(r.status == "duplicate" for r in out),
    )


@router.post("/{portfolio_id}/imports/commit")
async def import_commit(
    body: CsvIn,
    auth: CurrentAuth,
    portfolio: OwnedPortfolio,
    db: DbSession,
    fx: FxHistory,
    meta: Meta,
) -> CsvCommitOut:
    rows = await _parse(db, auth, portfolio, body)
    invalid = [r for r in rows if r.errors]
    if invalid and not body.skip_invalid:
        raise AppError(
            f"{len(invalid)} linha(s) com erro. Corrija o arquivo ou importe ignorando-as.",
            code="invalid_csv",
            status_code=422,
        )
    valid = [r for r in rows if r.data is not None and not r.duplicate]
    if valid:
        await service.create_transactions(
            db,
            fx,
            portfolio,
            [(r.data, csv_import.SOURCE, r.external_id) for r in valid if r.data],
            ip=meta.ip,
        )
    return CsvCommitOut(imported=len(valid), skipped=len(rows) - len(valid))
