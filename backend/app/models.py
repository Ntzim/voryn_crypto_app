"""Import every ORM model so SQLAlchemy metadata (and Alembic autogenerate) sees them."""

from app.core.db import Base
from app.modules.audit.models import AuditLog
from app.modules.auth.models import AuthToken, MfaRecoveryCode, UserSession
from app.modules.market_data.models import (
    Cryptocurrency,
    DailyPrice,
    FxRate,
    MarketPrice,
    MarketTicker,
)
from app.modules.portfolio.models import Exchange, Portfolio, Transaction
from app.modules.users.models import User, UserSettings

__all__ = [
    "AuditLog",
    "AuthToken",
    "Base",
    "Cryptocurrency",
    "DailyPrice",
    "Exchange",
    "FxRate",
    "MarketPrice",
    "MarketTicker",
    "MfaRecoveryCode",
    "Portfolio",
    "Transaction",
    "User",
    "UserSession",
    "UserSettings",
]
