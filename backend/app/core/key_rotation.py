"""Re-encrypt every secret at rest with the current ENCRYPTION_KEYS key.

Rotation procedure (docs/SECURITY_ARCHITECTURE.md):
1. Generate a key (scripts/generate_secrets.py) and set ENCRYPTION_KEYS="new,old".
   New values are encrypted with "new"; both keys still decrypt.
2. Run, in the API service:  python -m app.core.key_rotation
3. When it reports 0 failures, set ENCRYPTION_KEYS="new". The old key can be destroyed.

Idempotent: running it again re-encrypts with the same current key.
"""

import asyncio
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import DecryptionError, rotate
from app.core.logging import configure_logging, get_logger

logger = get_logger(__name__)


@dataclass(slots=True)
class RotationReport:
    rotated: int = 0
    failed: int = 0


async def rotate_all(db: AsyncSession) -> RotationReport:
    from app.modules.exchange_connections.models import ExchangeConnection
    from app.modules.users.models import User

    report = RotationReport()
    connections = (await db.execute(select(ExchangeConnection))).scalars()
    for conn in connections:
        try:
            conn.api_key_encrypted = rotate(conn.api_key_encrypted)
            conn.api_secret_encrypted = rotate(conn.api_secret_encrypted)
            report.rotated += 1
        except DecryptionError:
            report.failed += 1
            logger.error("key_rotation_failed", table="exchange_connections", id=str(conn.id))
    users = (await db.execute(select(User).where(User.mfa_secret_encrypted.is_not(None)))).scalars()
    for user in users:
        assert user.mfa_secret_encrypted is not None
        try:
            user.mfa_secret_encrypted = rotate(user.mfa_secret_encrypted)
            report.rotated += 1
        except DecryptionError:
            report.failed += 1
            logger.error("key_rotation_failed", table="users", id=str(user.id))
    await db.commit()
    logger.info("key_rotation_finished", rotated=report.rotated, failed=report.failed)
    return report


async def _main() -> RotationReport:
    from app import models as _models  # noqa: F401  (registers ORM mappers)
    from app.core.db import dispose_engine, get_sessionmaker

    try:
        async with get_sessionmaker()() as db:
            return await rotate_all(db)
    finally:
        await dispose_engine()


if __name__ == "__main__":
    configure_logging()
    result = asyncio.run(_main())
    print(f"rotated={result.rotated} failed={result.failed}")
    raise SystemExit(1 if result.failed else 0)
