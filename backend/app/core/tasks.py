"""Fire-and-forget background jobs, dispatched by task name to the Celery worker."""

import asyncio

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


async def enqueue(task_name: str) -> None:
    """Queue a worker task; failures are logged, never raised to the request."""
    if get_settings().background_tasks == "off":
        return
    from app.worker import celery_app

    try:
        await asyncio.to_thread(celery_app.send_task, task_name)
    except Exception:
        logger.exception("enqueue_failed", task=task_name)
