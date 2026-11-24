import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Response

from app.core.ai import AIClient, get_optional_ai_client
from app.core.config import get_settings
from app.core.exceptions import error_responses
from app.db.session import DbSession
from app.features.auth.deps import CurrentUser
from app.features.news import service
from app.features.news.models import InteractionKind, NewsCategory
from app.features.news.provider import NewsProvider, NullProvider
from app.features.news.schemas import (
    FeedPage,
    LikedState,
    NewsItemOut,
    NewsSourceOut,
    RefreshResult,
    SavedState,
)
from app.features.news.sources import AllSourcesProvider
from app.shared import refresh as scheduler
from app.shared.pagination import Page, Pagination

router = APIRouter(prefix="/news", tags=["news"], responses=error_responses(401))

OptionalAI = Annotated[AIClient | None, Depends(get_optional_ai_client)]


def get_news_provider() -> NewsProvider:
    return AllSourcesProvider() if get_settings().news_feeds_enabled else NullProvider()


Provider = Annotated[NewsProvider, Depends(get_news_provider)]


async def _maybe_refresh(tasks: BackgroundTasks, provider: NewsProvider) -> None:
    """Pull sources in the background when the last pull is older than NEWS_REFRESH_MINUTES."""
    settings = get_settings()
    if settings.news_feeds_enabled and await scheduler.claim("news", settings.news_refresh_minutes):
        tasks.add_task(service.run_refresh, provider)


@router.get("", response_model=Page[NewsItemOut], summary="News, newest first")
async def list_news(
    user: CurrentUser,
    db: DbSession,
    pagination: Pagination,
    tasks: BackgroundTasks,
    provider: Provider,
    category: NewsCategory | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    source: Annotated[str | None, Query(max_length=100)] = None,
) -> Page[NewsItemOut]:
    await _maybe_refresh(tasks, provider)
    return await service.list_news(db, user.id, pagination, category, q, source)


@router.get(
    "/feed",
    response_model=FeedPage,
    summary="For you: ranked by your interests, freshness and popularity, with AI notes",
)
async def feed(
    user: CurrentUser,
    db: DbSession,
    pagination: Pagination,
    tasks: BackgroundTasks,
    provider: Provider,
    ai: OptionalAI,
) -> FeedPage:
    await _maybe_refresh(tasks, provider)
    personalizing = False
    if (
        ai is not None
        and pagination.page == 1
        and await service.needs_insights(db, user.id)
        and await service.claim_insight_run(user.id)
    ):
        tasks.add_task(service.run_insights, user.id, ai)
        personalizing = True
    return await service.feed(db, user.id, pagination, personalizing)


@router.get("/sources", response_model=list[NewsSourceOut], summary="Sources for the stories row")
async def sources(_: CurrentUser, db: DbSession) -> list[NewsSourceOut]:
    return await service.sources(db)


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


@router.put("/{item_id}/like", response_model=LikedState, responses=error_responses(404))
async def like(item_id: uuid.UUID, user: CurrentUser, db: DbSession) -> LikedState:
    await service.interact(db, user.id, item_id, InteractionKind.LIKE, True)
    return LikedState(is_liked=True)


@router.delete("/{item_id}/like", response_model=LikedState, responses=error_responses(404))
async def unlike(item_id: uuid.UUID, user: CurrentUser, db: DbSession) -> LikedState:
    await service.interact(db, user.id, item_id, InteractionKind.LIKE, False)
    return LikedState(is_liked=False)


@router.put(
    "/{item_id}/hide",
    status_code=204,
    responses=error_responses(404),
    summary="Not interested: drop it from your feed and learn from it",
)
async def hide(item_id: uuid.UUID, user: CurrentUser, db: DbSession) -> Response:
    await service.interact(db, user.id, item_id, InteractionKind.HIDE, True)
    return Response(status_code=204)


@router.delete("/{item_id}/hide", status_code=204, responses=error_responses(404))
async def unhide(item_id: uuid.UUID, user: CurrentUser, db: DbSession) -> Response:
    await service.interact(db, user.id, item_id, InteractionKind.HIDE, False)
    return Response(status_code=204)


@router.post(
    "/{item_id}/open",
    status_code=204,
    responses=error_responses(404),
    summary="Record that you opened a story (a light interest signal)",
)
async def opened(item_id: uuid.UUID, user: CurrentUser, db: DbSession) -> Response:
    await service.interact(db, user.id, item_id, InteractionKind.OPEN, True)
    return Response(status_code=204)


@router.post(
    "/refresh",
    response_model=RefreshResult,
    summary="Pull every source now (a source that is down is skipped, never an error)",
)
async def refresh(_: CurrentUser, db: DbSession, provider: Provider) -> RefreshResult:
    return RefreshResult(added=await service.refresh(db, provider))
