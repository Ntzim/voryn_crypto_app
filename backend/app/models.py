"""Import every ORM model so SQLAlchemy metadata (and Alembic autogenerate) sees them."""

from app.core.db import Base
from app.modules.audit.models import AuditLog
from app.modules.auth.models import AuthToken, MfaRecoveryCode, UserSession
from app.modules.market_data.models import Cryptocurrency, FxRate, MarketPrice, MarketTicker
from app.modules.users.models import User, UserSettings

__all__ = [
    "AuditLog",
    "AuthToken",
    "Base",
    "Cryptocurrency",
    "FxRate",
    "MarketPrice",
    "MarketTicker",
    "MfaRecoveryCode",
    "User",
    "UserSession",
    "UserSettings",
]
