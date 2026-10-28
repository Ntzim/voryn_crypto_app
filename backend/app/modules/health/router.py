from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.db import get_sessionmaker
from app.core.logging import get_logger
from app.core.redis import get_redis
from app.modules.market_data.service import sync_status

router = APIRouter(prefix="/health", tags=["health"])
logger = get_logger(__name__)


@router.get("/live")
async def live() -> dict[str, str]:
    """Process is up. Used by the container orchestrator for restarts."""
    return {"status": "ok"}


@router.get("/ready")
async def ready() -> JSONResponse:
    """Dependencies reachable. Market data freshness is informational, not a failure."""
    checks: dict[str, Any] = {}
    healthy = True
    try:
        async with get_sessionmaker()() as session:
            await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        logger.warning("health_database_failed", error=str(exc))
        checks["database"] = "unavailable"
        healthy = False
    try:
        await get_redis().ping()
        checks["redis"] = "ok"
        checks["market_sync"] = await sync_status()
    except Exception as exc:
        logger.warning("health_redis_failed", error=str(exc))
        checks["redis"] = "unavailable"
        healthy = False
    return JSONResponse(
        {"status": "ok" if healthy else "degraded", "checks": checks},
        status_code=200 if healthy else 503,
    )
