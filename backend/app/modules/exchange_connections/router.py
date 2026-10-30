import uuid

from fastapi import APIRouter, status

from app.modules.auth.deps import CurrentAuth, DbSession, Meta
from app.modules.exchange_connections import service
from app.modules.exchange_connections.schemas import ConnectionIn, ConnectionOut, RecordOut
from app.modules.portfolio import service as portfolio

router = APIRouter(prefix="/exchange-connections", tags=["exchange-connections"])


def connector_factory() -> service.ConnectorFactory:
    return service.connector_for


@router.get("")
async def list_connections(auth: CurrentAuth, db: DbSession) -> list[ConnectionOut]:
    return [await service.out(db, c) for c in await service.list_connections(db, auth.user.id)]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_connection(
    body: ConnectionIn, auth: CurrentAuth, db: DbSession, meta: Meta
) -> ConnectionOut:
    """Connect a read-only API key. Keys with any trading, withdrawal or transfer
    permission are rejected. The first sync is queued immediately."""
    pf = (await portfolio.list_portfolios(db, auth.user.id))[0]
    conn = await service.create_connection(db, auth.user.id, pf, body, connector_factory(), meta.ip)
    return await service.out(db, conn)


@router.get("/{connection_id}")
async def get_connection(
    connection_id: uuid.UUID, auth: CurrentAuth, db: DbSession
) -> ConnectionOut:
    return await service.out(db, await service.get_owned(db, auth.user.id, connection_id))


@router.get("/{connection_id}/records")
async def review_records(
    connection_id: uuid.UUID, auth: CurrentAuth, db: DbSession
) -> list[RecordOut]:
    """Synced records not imported into the portfolio, with the reason."""
    conn = await service.get_owned(db, auth.user.id, connection_id)
    return await service.review_records(db, conn)


@router.post("/{connection_id}/sync", status_code=status.HTTP_202_ACCEPTED)
async def sync_connection(
    connection_id: uuid.UUID, auth: CurrentAuth, db: DbSession
) -> ConnectionOut:
    conn = await service.get_owned(db, auth.user.id, connection_id)
    await service.request_sync(db, conn)
    return await service.out(db, conn)


@router.delete("/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_connection(
    connection_id: uuid.UUID, auth: CurrentAuth, db: DbSession, meta: Meta
) -> None:
    """Delete the credentials and synced records. Imported transactions are kept."""
    conn = await service.get_owned(db, auth.user.id, connection_id)
    await service.delete_connection(db, conn, meta.ip)
