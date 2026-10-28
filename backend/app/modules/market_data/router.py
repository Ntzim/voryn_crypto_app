from typing import Annotated, Literal

from fastapi import APIRouter, Path, Query

from app.modules.auth.deps import CurrentAuth, DbSession
from app.modules.market_data import service
from app.modules.market_data.schemas import (
    AssetBriefOut,
    AssetDetailOut,
    AssetListOut,
    MarketOverviewOut,
    QuoteCurrency,
    SortKey,
)

router = APIRouter(prefix="/market", tags=["market"])


@router.get("/assets")
async def list_assets(
    _: CurrentAuth,
    db: DbSession,
    currency: QuoteCurrency = "USD",
    q: Annotated[str | None, Query(max_length=64)] = None,
    sort: SortKey = "rank",
    order: Literal["asc", "desc"] = "asc",
    page: Annotated[int, Query(ge=1, le=1000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> AssetListOut:
    return await service.list_assets(
        db, currency=currency, q=q, sort=sort, order=order, page=page, page_size=page_size
    )


@router.get("/search")
async def search_assets(
    _: CurrentAuth, db: DbSession, q: Annotated[str, Query(min_length=1, max_length=64)]
) -> list[AssetBriefOut]:
    """Asset picker: catalogue search by name or symbol, best-ranked first."""
    return [
        AssetBriefOut(
            id=c.id, slug=c.source_id, symbol=c.symbol, name=c.name, image_url=c.image_url
        )
        for c in await service.search_assets(db, q)
    ]


@router.get("/assets/{slug}")
async def get_asset(
    _: CurrentAuth,
    db: DbSession,
    slug: Annotated[str, Path(max_length=128, pattern=r"^[a-z0-9-]+$")],
    currency: QuoteCurrency = "USD",
) -> AssetDetailOut:
    return await service.get_asset(db, slug, currency)


@router.get("/overview")
async def overview(
    _: CurrentAuth, db: DbSession, currency: QuoteCurrency = "USD"
) -> MarketOverviewOut:
    return await service.overview(db, currency)
