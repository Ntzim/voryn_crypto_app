"""Watchlists: a default "Favoritos" list (created lazily) plus user-defined lists."""

import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ConflictError, NotFoundError
from app.modules.market_data.models import Cryptocurrency
from app.modules.watchlists.models import Watchlist, WatchlistAsset

DEFAULT_NAME = "Favoritos"
MAX_LISTS = 20
MAX_ASSETS = 200


async def list_watchlists(
    db: AsyncSession, user_id: uuid.UUID
) -> list[tuple[Watchlist, list[uuid.UUID]]]:
    lists = list(
        (
            await db.execute(
                select(Watchlist)
                .where(Watchlist.user_id == user_id)
                .order_by(Watchlist.is_default.desc(), Watchlist.created_at)
            )
        ).scalars()
    )
    if not lists:
        default = Watchlist(user_id=user_id, name=DEFAULT_NAME, is_default=True)
        db.add(default)
        try:
            await db.commit()
        except IntegrityError:  # created concurrently by another request
            await db.rollback()
            return await list_watchlists(db, user_id)
        lists = [default]
    rows = (
        await db.execute(
            select(WatchlistAsset.watchlist_id, WatchlistAsset.cryptocurrency_id)
            .where(WatchlistAsset.watchlist_id.in_([w.id for w in lists]))
            .order_by(WatchlistAsset.added_at)
        )
    ).all()
    members: dict[uuid.UUID, list[uuid.UUID]] = {w.id: [] for w in lists}
    for watchlist_id, crypto_id in rows:
        members[watchlist_id].append(crypto_id)
    return [(w, members[w.id]) for w in lists]


async def get_owned(db: AsyncSession, user_id: uuid.UUID, watchlist_id: uuid.UUID) -> Watchlist:
    """Ownership check: other users' lists are indistinguishable from missing ones."""
    watchlist = (
        await db.execute(
            select(Watchlist).where(Watchlist.id == watchlist_id, Watchlist.user_id == user_id)
        )
    ).scalar_one_or_none()
    if watchlist is None:
        raise NotFoundError("Lista não encontrada.")
    return watchlist


async def create(db: AsyncSession, user_id: uuid.UUID, name: str) -> Watchlist:
    await list_watchlists(db, user_id)  # ensure the default list exists first
    count = await db.scalar(select(func.count()).where(Watchlist.user_id == user_id)) or 0
    if count >= MAX_LISTS:
        raise AppError(f"Limite de {MAX_LISTS} listas atingido.", code="limit_reached")
    watchlist = Watchlist(user_id=user_id, name=name)
    db.add(watchlist)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError("Já existe uma lista com esse nome.") from exc
    return watchlist


async def rename(db: AsyncSession, watchlist: Watchlist, name: str) -> Watchlist:
    watchlist.name = name
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError("Já existe uma lista com esse nome.") from exc
    return watchlist


async def remove(db: AsyncSession, watchlist: Watchlist) -> None:
    if watchlist.is_default:
        raise AppError("A lista de favoritos não pode ser excluída.", code="default_watchlist")
    await db.delete(watchlist)
    await db.commit()


async def add_asset(db: AsyncSession, watchlist: Watchlist, asset_id: uuid.UUID) -> None:
    if await db.get(Cryptocurrency, asset_id) is None:
        raise NotFoundError("Ativo não encontrado.")
    count = (
        await db.scalar(select(func.count()).where(WatchlistAsset.watchlist_id == watchlist.id))
        or 0
    )
    if count >= MAX_ASSETS:
        raise AppError(f"Uma lista comporta até {MAX_ASSETS} ativos.", code="limit_reached")
    await db.execute(
        insert(WatchlistAsset)
        .values(watchlist_id=watchlist.id, cryptocurrency_id=asset_id)
        .on_conflict_do_nothing()
    )
    await db.commit()


async def remove_asset(db: AsyncSession, watchlist: Watchlist, asset_id: uuid.UUID) -> None:
    await db.execute(
        delete(WatchlistAsset).where(
            WatchlistAsset.watchlist_id == watchlist.id,
            WatchlistAsset.cryptocurrency_id == asset_id,
        )
    )
    await db.commit()


async def asset_ids(db: AsyncSession, watchlist: Watchlist) -> list[uuid.UUID]:
    return list(
        (
            await db.execute(
                select(WatchlistAsset.cryptocurrency_id).where(
                    WatchlistAsset.watchlist_id == watchlist.id
                )
            )
        ).scalars()
    )
