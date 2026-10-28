import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field, field_validator

from app.modules.auth.deps import CurrentAuth, DbSession
from app.modules.watchlists import service
from app.modules.watchlists.models import Watchlist

router = APIRouter(prefix="/watchlists", tags=["watchlists"])


class WatchlistIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)

    @field_validator("name")
    @classmethod
    def _clean(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("Informe um nome.")
        return value


class WatchlistOut(BaseModel):
    id: uuid.UUID
    name: str
    is_default: bool
    asset_ids: list[uuid.UUID]


async def owned(watchlist_id: uuid.UUID, auth: CurrentAuth, db: DbSession) -> Watchlist:
    return await service.get_owned(db, auth.user.id, watchlist_id)


Owned = Annotated[Watchlist, Depends(owned)]


def _out(watchlist: Watchlist, asset_ids: list[uuid.UUID]) -> WatchlistOut:
    return WatchlistOut(
        id=watchlist.id, name=watchlist.name, is_default=watchlist.is_default, asset_ids=asset_ids
    )


@router.get("")
async def list_watchlists(auth: CurrentAuth, db: DbSession) -> list[WatchlistOut]:
    """The user's lists; the default "Favoritos" list is created on first access."""
    return [_out(w, ids) for w, ids in await service.list_watchlists(db, auth.user.id)]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_watchlist(data: WatchlistIn, auth: CurrentAuth, db: DbSession) -> WatchlistOut:
    return _out(await service.create(db, auth.user.id, data.name), [])


@router.patch("/{watchlist_id}")
async def rename_watchlist(data: WatchlistIn, watchlist: Owned, db: DbSession) -> WatchlistOut:
    await service.rename(db, watchlist, data.name)
    return _out(watchlist, await service.asset_ids(db, watchlist))


@router.delete("/{watchlist_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_watchlist(watchlist: Owned, db: DbSession) -> None:
    await service.remove(db, watchlist)


@router.put("/{watchlist_id}/assets/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def add_asset(asset_id: uuid.UUID, watchlist: Owned, db: DbSession) -> None:
    await service.add_asset(db, watchlist, asset_id)


@router.delete("/{watchlist_id}/assets/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_asset(asset_id: uuid.UUID, watchlist: Owned, db: DbSession) -> None:
    await service.remove_asset(db, watchlist, asset_id)
