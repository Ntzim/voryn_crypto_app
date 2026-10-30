"""Resource-level authorization: the single way a route loads a user-owned row by id.

The owner always comes from the session (`user_id` argument), never from the request.
A row owned by someone else answers exactly like a missing one (404, so ids cannot be
probed), but the attempt is audited and counted, because a signed-in user asking for
another user's resource by id is either a bug or an attack.
"""

import uuid
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security_events
from app.core.errors import NotFoundError
from app.core.middleware import current_client_ip


class Owned(Protocol):
    user_id: Any


async def deny(user_id: uuid.UUID, resource: str, resource_id: object) -> None:
    """Audit and count an attempt to reach another user's resource."""
    from app.modules.audit.service import AuditAction, record_now

    await security_events.emit(
        "access_denied", user_id=str(user_id), resource=resource, resource_id=str(resource_id)
    )
    await record_now(
        AuditAction.ACCESS_DENIED,
        user_id=user_id,
        ip_address=current_client_ip(),
        resource=resource,
        resource_id=str(resource_id),
    )


async def owned_or_404[T: Owned](
    db: AsyncSession, model: type[T], resource_id: object, user_id: uuid.UUID, message: str
) -> T:
    row = await db.get(model, resource_id)
    if row is None or row.user_id != user_id:
        if row is not None:
            await deny(user_id, getattr(model, "__tablename__", model.__name__), resource_id)
        raise NotFoundError(message)
    return row
