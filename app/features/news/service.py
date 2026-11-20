"""News list (cached per category/query/page for everyone) + per-user saved state."""

import uuid
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import NotFoundError
from app.core.redis import bump_version, cache_get, cache_set, cache_version
from app.features.dashboard.cache import invalidate_dashboard
from app.features.jobs.service import escape_like
from app.features.news.models import NewsCategory, NewsItem, SavedNews
from app.features.news.provider import NewsProvider
from app.features.news.schemas import NewsItemOut
from app.shared.pagination import Page, PageParams, paginate

NEWS_SCOPE = "news"


async def saved_ids(
    db: AsyncSession, user_id: uuid.UUID, item_ids: list[uuid.UUID]
) -> set[uuid.UUID]:
    if not item_ids:
        return set()
    rows = await db.scalars(
        select(SavedNews.news_item_id).where(
            SavedNews.user_id == user_id, SavedNews.news_item_id.in_(item_ids)
        )
    )
    return set(rows)


async def _public_page(
    db: AsyncSession, category: NewsCategory | None, q: str | None, params: PageParams
) -> dict[str, Any]:
    q = (q or "").strip()
    version = await cache_version(NEWS_SCOPE)
    key = f"cache:news:v{version}:{category or 'all'}:{params.page}:{params.size}:{q.lower()}"
    cached = await cache_get(key)
    if cached is not None:
        return dict(cached)
    stmt = select(NewsItem)
    if category is not None:
        stmt = stmt.where(NewsItem.category == category)
    if q:
        pattern = f"%{escape_like(q)}%"
        stmt = stmt.where(
            NewsItem.title.ilike(pattern, escape="\\")
            | NewsItem.summary.ilike(pattern, escape="\\")
        )
    stmt = stmt.order_by(NewsItem.published_at.desc(), NewsItem.id)
    items, total = await paginate(db, stmt, params)
    payload = {
        "items": [NewsItemOut.model_validate(i).model_dump(mode="json") for i in items],
        "total": total,
    }
    await cache_set(key, payload, get_settings().news_cache_seconds)
    return payload


async def list_news(
    db: AsyncSession,
    user_id: uuid.UUID,
    params: PageParams,
    category: NewsCategory | None = None,
    q: str | None = None,
) -> Page[NewsItemOut]:
    payload = await _public_page(db, category, q, params)
    items = [NewsItemOut.model_validate(i) for i in payload["items"]]
    # Saved state is per user, so it is merged after the shared cache.
    saved = await saved_ids(db, user_id, [i.id for i in items])
    for item in items:
        item.is_saved = item.id in saved
    return Page[NewsItemOut].build(items, int(payload["total"]), params)


async def latest(db: AsyncSession, user_id: uuid.UUID, limit: int = 3) -> list[NewsItemOut]:
    page = await list_news(db, user_id, PageParams(page=1, size=limit))
    return page.items


async def list_saved(db: AsyncSession, user_id: uuid.UUID, params: PageParams) -> Page[NewsItemOut]:
    stmt = (
        select(NewsItem)
        .join(SavedNews, SavedNews.news_item_id == NewsItem.id)
        .where(SavedNews.user_id == user_id)
        .order_by(SavedNews.created_at.desc(), NewsItem.id)
    )
    items, total = await paginate(db, stmt, params)
    out = [NewsItemOut.model_validate(i).model_copy(update={"is_saved": True}) for i in items]
    return Page[NewsItemOut].build(out, total, params)


async def _ensure_item(db: AsyncSession, item_id: uuid.UUID) -> None:
    if await db.scalar(select(NewsItem.id).where(NewsItem.id == item_id)) is None:
        raise NotFoundError("News item not found", code="NEWS_NOT_FOUND")


async def save(db: AsyncSession, user_id: uuid.UUID, item_id: uuid.UUID) -> None:
    await _ensure_item(db, item_id)
    await db.execute(
        insert(SavedNews)
        .values(id=uuid.uuid4(), user_id=user_id, news_item_id=item_id)
        .on_conflict_do_nothing(index_elements=["user_id", "news_item_id"])
    )
    await db.commit()
    await invalidate_dashboard(user_id)


async def unsave(db: AsyncSession, user_id: uuid.UUID, item_id: uuid.UUID) -> None:
    await _ensure_item(db, item_id)
    await db.execute(
        delete(SavedNews).where(SavedNews.user_id == user_id, SavedNews.news_item_id == item_id)
    )
    await db.commit()
    await invalidate_dashboard(user_id)


async def refresh(db: AsyncSession, provider: NewsProvider) -> int:
    """Pull from the provider and insert new URLs. Never raises for a failing source."""
    fetched = await provider.fetch()
    if not fetched:
        return 0
    unique = {f.url: f for f in fetched}
    rows = [
        {
            "id": uuid.uuid4(),
            "title": f.title,
            "source": f.source,
            "url": f.url,
            "summary": f.summary,
            "image_url": f.image_url,
            "category": f.category,
            "published_at": f.published_at,
        }
        for f in unique.values()
    ]
    result = await db.scalars(
        insert(NewsItem)
        .values(rows)
        .on_conflict_do_nothing(index_elements=["url"])
        .returning(NewsItem.id)
    )
    added = len(result.all())
    await db.commit()
    if added:
        await bump_version(NEWS_SCOPE)
    return added
