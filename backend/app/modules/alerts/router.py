import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.modules.alerts import service
from app.modules.alerts.models import Alert
from app.modules.alerts.schemas import AlertIn, AlertOut, NotificationListOut
from app.modules.auth.deps import CurrentAuth, DbSession

router = APIRouter(prefix="/alerts", tags=["alerts"])
notifications_router = APIRouter(prefix="/notifications", tags=["alerts"])


async def owned(alert_id: uuid.UUID, auth: CurrentAuth, db: DbSession) -> Alert:
    return await service.get_owned(db, auth.user.id, alert_id)


Owned = Annotated[Alert, Depends(owned)]


@router.get("")
async def list_alerts(auth: CurrentAuth, db: DbSession) -> list[AlertOut]:
    return await service.list_alerts(db, auth.user.id)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_alert(data: AlertIn, auth: CurrentAuth, db: DbSession) -> AlertOut:
    return await service.create(db, auth.user.id, data)


@router.put("/{alert_id}")
async def update_alert(data: AlertIn, alert: Owned, db: DbSession) -> AlertOut:
    return await service.update_alert(db, alert, data)


@router.delete("/{alert_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_alert(alert: Owned, db: DbSession) -> None:
    await service.delete_alert(db, alert)


@notifications_router.get("")
async def list_notifications(
    auth: CurrentAuth,
    db: DbSession,
    unread_only: bool = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> NotificationListOut:
    items, unread, total = await service.list_notifications(
        db, auth.user.id, unread_only=unread_only, limit=limit
    )
    return NotificationListOut(items=items, unread=unread, total=total)


@notifications_router.post("/read-all", status_code=status.HTTP_204_NO_CONTENT)
async def read_all(auth: CurrentAuth, db: DbSession) -> None:
    await service.mark_read(db, auth.user.id, None)


@notifications_router.post("/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def read_one(notification_id: int, auth: CurrentAuth, db: DbSession) -> None:
    await service.mark_read(db, auth.user.id, notification_id)
