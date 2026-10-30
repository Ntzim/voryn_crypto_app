from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.modules.auth.deps import DbSession, user_rate_limit
from app.modules.market_data.providers.base import CandleProvider
from app.modules.portfolio.router import OwnedPortfolio, ReportingCurrency
from app.modules.risk import service
from app.modules.risk.schemas import RiskOut, ScenarioIn, ScenarioOut
from app.modules.technical_analysis.router import get_candle_provider

router = APIRouter(prefix="/portfolios", tags=["risk"])

Candles = Annotated[CandleProvider, Depends(get_candle_provider)]


@router.get("/{portfolio_id}/risk", dependencies=[user_rate_limit("risk", 30, 60)])
async def portfolio_risk(
    portfolio: OwnedPortfolio,
    db: DbSession,
    currency: ReportingCurrency,
    provider: Candles,
    window: Annotated[int, Query(ge=30, le=365)] = 365,
) -> RiskOut:
    """Volatility, drawdown, historical VaR, beta, correlation, concentration and liquidity
    of the current holdings over their daily price history."""
    return await service.portfolio_risk(db, portfolio, currency, window, provider)


@router.post("/{portfolio_id}/risk/scenario", dependencies=[user_rate_limit("risk", 30, 60)])
async def risk_scenario(
    portfolio: OwnedPortfolio,
    db: DbSession,
    currency: ReportingCurrency,
    provider: Candles,
    body: ScenarioIn,
) -> ScenarioOut:
    """What-if: a Bitcoin move propagated by beta, with optional per-asset overrides.
    Read-only: nothing is stored."""
    return await service.scenario(db, portfolio, currency, body, provider)
