import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.config import get_settings
from app.core.exceptions import error_responses
from app.db.session import DbSession
from app.features.auth.deps import CurrentUser
from app.features.news import service
from app.features.news.models import NewsCategory
from app.features.news.provider import NewsProvider, NullProvider, RSSProvider
from app.features.news.schemas import NewsItemOut, RefreshResult, SavedState
from app.shared.pagination import Page, Pagination

router = APIRouter(prefix="/news", tags=["news"], responses=error_responses(401))


def get_news_provider() -> NewsProvider:
    return RSSProvider() if get_settings().news_feeds_enabled else NullProvider()


@router.get("", response_model=Page[NewsItemOut], summary="News, newest first")
async def list_news(
    user: CurrentUser,
    db: DbSession,
    pagination: Pagination,
    category: NewsCategory | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
) -> Page[NewsItemOut]:
    return await service.list_news(db, user.id, pagination, category, q)


@router.get("/saved", response_model=Page[NewsItemOut], summary="Saved items, newest save first")
async def list_saved(user: CurrentUser, db: DbSession, pagination: Pagination) -> Page[NewsItemOut]:
    return await service.list_saved(db, user.id, pagination)


@router.put("/{item_id}/save", response_model=SavedState, responses=error_responses(404))
async def save(item_id: uuid.UUID, user: CurrentUser, db: DbSession) -> SavedState:
    await service.save(db, user.id, item_id)
    return SavedState(is_saved=True)


@router.delete("/{item_id}/save", response_model=SavedState, responses=error_responses(404))
async def unsave(item_id: uuid.UUID, user: CurrentUser, db: DbSession) -> SavedState:
    await service.unsave(db, user.id, item_id)
    return SavedState(is_saved=False)


@router.post(
    "/refresh",
    response_model=RefreshResult,
    summary="Pull RSS feeds now (a feed that is down is skipped, never an error)",
)
async def refresh(
    _: CurrentUser,
    db: DbSession,
    provider: Annotated[NewsProvider, Depends(get_news_provider)],
) -> RefreshResult:
    return RefreshResult(added=await service.refresh(db, provider))
