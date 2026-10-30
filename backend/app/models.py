"""Import every ORM model so SQLAlchemy metadata (and Alembic autogenerate) sees them."""

from app.core.db import Base
from app.modules.ai.models import AIConversation, AIMessage
from app.modules.alerts.models import Alert, Notification
from app.modules.audit.models import AuditLog
from app.modules.auth.models import AuthToken, MfaRecoveryCode, UserSession
from app.modules.backtesting.models import BacktestRun
from app.modules.market_data.models import (
    Cryptocurrency,
    DailyPrice,
    FxRate,
    HistoricalCandle,
    MarketPrice,
    MarketTicker,
)
from app.modules.portfolio.models import Exchange, Portfolio, Transaction
from app.modules.signals.models import AnalysisSignal, SignalStrategy
from app.modules.users.models import User, UserSettings
from app.modules.watchlists.models import Watchlist, WatchlistAsset

__all__ = [
    "AIConversation",
    "AIMessage",
    "Alert",
    "AnalysisSignal",
    "AuditLog",
    "AuthToken",
    "BacktestRun",
    "Base",
    "Cryptocurrency",
    "DailyPrice",
    "Exchange",
    "FxRate",
    "HistoricalCandle",
    "MarketPrice",
    "MarketTicker",
    "MfaRecoveryCode",
    "Notification",
    "Portfolio",
    "SignalStrategy",
    "Transaction",
    "User",
    "UserSession",
    "UserSettings",
    "Watchlist",
    "WatchlistAsset",
]
