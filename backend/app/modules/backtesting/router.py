import uuid

from fastapi import APIRouter, status

from app.modules.auth.deps import CurrentAuth, DbSession
from app.modules.backtesting import service
from app.modules.backtesting.schemas import (
    BacktestIn,
    BacktestOut,
    BacktestSummaryOut,
    StrategyInfoOut,
)

router = APIRouter(prefix="/backtests", tags=["backtesting"])


@router.get("/strategies")
async def strategies(_: CurrentAuth) -> list[StrategyInfoOut]:
    return service.CATALOGUE


@router.get("")
async def list_backtests(auth: CurrentAuth, db: DbSession) -> list[BacktestSummaryOut]:
    return await service.summaries(db, await service.list_runs(db, auth.user.id))


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def create_backtest(auth: CurrentAuth, db: DbSession, body: BacktestIn) -> BacktestOut:
    """Queue a backtest; poll GET /backtests/{id} until status is done or failed."""
    run = await service.create_run(db, auth.user.id, body)
    return await service.detail(db, run)


@router.get("/{run_id}")
async def get_backtest(run_id: uuid.UUID, auth: CurrentAuth, db: DbSession) -> BacktestOut:
    return await service.detail(db, await service.get_owned(db, auth.user.id, run_id))


@router.delete("/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_backtest(run_id: uuid.UUID, auth: CurrentAuth, db: DbSession) -> None:
    await service.delete_run(db, await service.get_owned(db, auth.user.id, run_id))
