"""News: the shared list (cached), the personal "For you" feed, likes/hides/saves, and refresh."""

import asyncio
import math
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ai import AIClient
from app.core.config import get_settings
from app.core.exceptions import AppError, NotFoundError
from app.core.logging import get_logger
from app.core.redis import bump_version, cache_get, cache_set, cache_version, get_redis
from app.features.auth.models import User
from app.features.dashboard.cache import invalidate_dashboard
from app.features.jobs.service import escape_like
from app.features.news.models import (
    InteractionKind,
    NewsCategory,
    NewsInsight,
    NewsInteraction,
    NewsItem,
    SavedNews,
)
from app.features.news.provider import FetchedNews, NewsProvider
from app.features.news.schemas import FeedPage, NewsInsightOut, NewsItemOut, NewsSourceOut
from app.features.personalize import service as interests
from app.features.personalize.models import SearchScope
from app.shared.pagination import Page, PageParams, paginate
from app.shared.text import token_set

log = get_logger(__name__)

NEWS_SCOPE = "news"
FEED_WINDOW_DAYS = 10
FEED_POOL = 600
FEED_CACHE_SECONDS = 300
INSIGHT_BATCH = 20
INSIGHT_COOLDOWN_SECONDS = 600
RETENTION_DAYS = 45


# ---- per-user state merged onto shared items ------------------------------------------------


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


async def _interaction_ids(
    db: AsyncSession,
    user_id: uuid.UUID,
    kind: InteractionKind,
    item_ids: list[uuid.UUID] | None,
) -> set[uuid.UUID]:
    stmt = select(NewsInteraction.news_item_id).where(
        NewsInteraction.user_id == user_id, NewsInteraction.kind == kind
    )
    if item_ids is not None:
        if not item_ids:
            return set()
        stmt = stmt.where(NewsInteraction.news_item_id.in_(item_ids))
    return set(await db.scalars(stmt))


async def _insights(
    db: AsyncSession, user_id: uuid.UUID, item_ids: list[uuid.UUID]
) -> dict[uuid.UUID, NewsInsightOut]:
    if not item_ids:
        return {}
    rows = await db.scalars(
        select(NewsInsight).where(
            NewsInsight.user_id == user_id, NewsInsight.news_item_id.in_(item_ids)
        )
    )
    return {r.news_item_id: NewsInsightOut(relevance=r.relevance, reason=r.reason) for r in rows}


async def _decorate(db: AsyncSession, user_id: uuid.UUID, items: list[NewsItemOut]) -> None:
    ids = [i.id for i in items]
    saved = await saved_ids(db, user_id, ids)
    liked = await _interaction_ids(db, user_id, InteractionKind.LIKE, ids)
    insights = await _insights(db, user_id, ids)
    for item in items:
        item.is_saved = item.id in saved
        item.is_liked = item.id in liked
        item.insight = insights.get(item.id)


# ---- shared list ---------------------------------------------------------------------------


async def _public_page(
    db: AsyncSession,
    category: NewsCategory | None,
    q: str | None,
    source: str | None,
    params: PageParams,
) -> dict[str, Any]:
    q = (q or "").strip()
    version = await cache_version(NEWS_SCOPE)
    key = (
        f"cache:news:v{version}:{category or 'all'}:{source or 'any'}:"
        f"{params.page}:{params.size}:{q.lower()}"
    )
    cached = await cache_get(key)
    if cached is not None:
        return dict(cached)
    stmt = select(NewsItem)
    if category is not None:
        stmt = stmt.where(NewsItem.category == category)
    if source:
        stmt = stmt.where(NewsItem.source == source)
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
    source: str | None = None,
) -> Page[NewsItemOut]:
    if q and params.page == 1:
        await interests.record_search(db, user_id, SearchScope.NEWS, q)
    payload = await _public_page(db, category, q, source, params)
    items = [NewsItemOut.model_validate(i) for i in payload["items"]]
    # Saved/liked state is per user, so it is merged after the shared cache.
    await _decorate(db, user_id, items)
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
    out = [NewsItemOut.model_validate(i) for i in items]
    await _decorate(db, user_id, out)
    return Page[NewsItemOut].build(out, total, params)


async def sources(db: AsyncSession, limit: int = 20) -> list[NewsSourceOut]:
    """Sources with stories in the last two days, busiest first (the stories row)."""
    since = datetime.now(UTC) - timedelta(days=2)
    rows = await db.execute(
        select(
            NewsItem.source,
            func.count(),
            func.max(NewsItem.published_at),
            func.max(NewsItem.image_url),
        )
        .where(NewsItem.published_at >= since)
        .group_by(NewsItem.source)
        .order_by(func.count().desc(), func.max(NewsItem.published_at).desc())
        .limit(limit)
    )
    return [
        NewsSourceOut(source=s, count=c, latest_at=at, preview_image=img) for s, c, at, img in rows
    ]


# ---- personal feed -------------------------------------------------------------------------


def _popularity(item: NewsItem) -> float:
    signal = (item.score or 0) + 2 * (item.comments or 0)
    if signal <= 0:
        return 0.25  # blogs don't report votes: treat as average
    return min(1.0, math.log1p(signal) / math.log1p(3000))


def rank(
    items: list[NewsItem],
    weights: dict[str, float],
    insights: dict[uuid.UUID, int],
    opened: set[uuid.UUID],
    now: datetime,
) -> list[uuid.UUID]:
    """Order by personal match, AI relevance, freshness and popularity, keeping sources varied."""
    scored: list[tuple[float, NewsItem]] = []
    for item in items:
        words = token_set(item.title, item.summary) | set(item.tags or [])
        personal = interests.match(weights, words, item.title)
        if personal < 0:
            continue  # hits a muted topic
        age_hours = max(0.0, (now - item.published_at).total_seconds() / 3600)
        score = (
            0.45 * personal
            + 0.25 * math.exp(-age_hours / 30)
            + 0.20 * _popularity(item)
            + (0.35 * insights[item.id] / 100 if item.id in insights else 0.0)
            - (0.15 if item.id in opened else 0.0)
        )
        scored.append((score, item))
    scored.sort(key=lambda s: s[0], reverse=True)

    ordered: list[uuid.UUID] = []
    recent: list[str] = []
    pending = [item for _, item in scored]
    while pending:
        pick = next((i for i, it in enumerate(pending[:8]) if recent[-2:].count(it.source) < 2), 0)
        item = pending.pop(pick)
        ordered.append(item.id)
        recent.append(item.source)
    return ordered


async def _feed_order(db: AsyncSession, user_id: uuid.UUID) -> list[uuid.UUID]:
    news_v = await cache_version(NEWS_SCOPE)
    me_v = await cache_version(interests.scope_key(user_id))
    key = f"cache:feed:{user_id}:n{news_v}:i{me_v}"
    cached = await cache_get(key)
    if cached is not None:
        return [uuid.UUID(i) for i in cached]
    now = datetime.now(UTC)
    hidden = await _interaction_ids(db, user_id, InteractionKind.HIDE, None)
    recent = await db.scalars(
        select(NewsItem)
        .where(NewsItem.published_at >= now - timedelta(days=FEED_WINDOW_DAYS))
        .order_by(NewsItem.published_at.desc())
        .limit(FEED_POOL)
    )
    pool = [i for i in recent if i.id not in hidden]
    if len(pool) < 30:  # quiet stretch or first run: fall back to the newest overall
        older = await db.scalars(
            select(NewsItem).order_by(NewsItem.published_at.desc()).limit(FEED_POOL)
        )
        pool = [i for i in older if i.id not in hidden]
    weights = await interests.terms(db, user_id)
    insight_rows = await db.execute(
        select(NewsInsight.news_item_id, NewsInsight.relevance).where(
            NewsInsight.user_id == user_id
        )
    )
    insight_map: dict[uuid.UUID, int] = {row[0]: row[1] for row in insight_rows}
    opened = await _interaction_ids(db, user_id, InteractionKind.OPEN, None)
    order = rank(pool, weights, insight_map, opened, now)
    await cache_set(key, [str(i) for i in order], FEED_CACHE_SECONDS)
    return order


async def feed(
    db: AsyncSession, user_id: uuid.UUID, params: PageParams, personalizing: bool = False
) -> FeedPage:
    order = await _feed_order(db, user_id)
    page_ids = order[params.offset : params.offset + params.size]
    rows = {i.id: i for i in await db.scalars(select(NewsItem).where(NewsItem.id.in_(page_ids)))}
    items = [NewsItemOut.model_validate(rows[i]) for i in page_ids if i in rows]
    await _decorate(db, user_id, items)
    base = Page[NewsItemOut].build(items, len(order), params)
    return FeedPage(**base.model_dump(exclude={"items"}), items=items, personalizing=personalizing)


async def needs_insights(db: AsyncSession, user_id: uuid.UUID) -> list[uuid.UUID]:
    """Top feed items the AI hasn't rated yet."""
    head = (await _feed_order(db, user_id))[: INSIGHT_BATCH * 2]
    if not head:
        return []
    have = set(
        await db.scalars(
            select(NewsInsight.news_item_id).where(
                NewsInsight.user_id == user_id, NewsInsight.news_item_id.in_(head)
            )
        )
    )
    return [i for i in head if i not in have][:INSIGHT_BATCH]


class RatedStory(BaseModel):
    n: int = Field(description="The number of the story in the list")
    relevance: int = Field(description="0-100: how useful this story is to this reader")
    reason: str = Field(description="At most 18 words, addressed to the reader, concrete")


class RatedStories(BaseModel):
    items: list[RatedStory]


INSIGHT_SYSTEM = """You curate a personal tech news feed for one reader.
Rate every numbered story for how useful it is to THIS reader, from 0 (irrelevant) to 100
(directly affects their work, skills, stack or job search). Use the reader context.
For each story write `reason`: at most 18 words, addressed to the reader ("you"), concrete about
the connection (their stack, target role, interests). If it is not relevant, say so briefly.
Never invent facts about the story beyond its title and summary."""


async def write_insights(
    db: AsyncSession, user: User, ai: AIClient, item_ids: list[uuid.UUID]
) -> int:
    if not item_ids:
        return 0
    found = {i.id: i for i in await db.scalars(select(NewsItem).where(NewsItem.id.in_(item_ids)))}
    items = [found[i] for i in item_ids if i in found]
    if not items:
        return 0
    ctx = await interests.context(db, user)
    listing = "\n".join(
        f"{n}. [{it.source}] {it.title} — {it.summary[:220]}"
        + (f" (tags: {', '.join(it.tags[:6])})" if it.tags else "")
        for n, it in enumerate(items, start=1)
    )
    result = await ai.generate_structured(
        system=INSIGHT_SYSTEM,
        prompt=f"Reader context:\n{ctx}\n\nStories:\n{listing}",
        schema=RatedStories,
    )
    by_n = {r.n: r for r in result.items}
    rows = [
        {
            "id": uuid.uuid4(),
            "user_id": user.id,
            "news_item_id": it.id,
            "relevance": max(0, min(100, by_n[n].relevance)),
            "reason": by_n[n].reason.strip()[:300],
        }
        for n, it in enumerate(items, start=1)
        if n in by_n
    ]
    if rows:
        stmt = insert(NewsInsight).values(rows)
        await db.execute(
            stmt.on_conflict_do_update(
                index_elements=["user_id", "news_item_id"],
                set_={"relevance": stmt.excluded.relevance, "reason": stmt.excluded.reason},
            )
        )
        await db.commit()
        await interests.touch(user.id)
    return len(rows)


async def claim_insight_run(user_id: uuid.UUID) -> bool:
    """At most one AI rating run per user per cooldown (free Gemini quota is small)."""
    try:
        return bool(
            await get_redis().set(
                f"lock:insights:{user_id}", "1", ex=INSIGHT_COOLDOWN_SECONDS, nx=True
            )
        )
    except Exception:
        return False


async def run_insights(user_id: uuid.UUID, ai: AIClient) -> None:
    """Background job: open a fresh session and rate the top of the feed."""
    from app.db.session import SessionLocal

    async with SessionLocal() as db:
        user = await db.get(User, user_id)
        if user is None:
            return
        try:
            await write_insights(db, user, ai, await needs_insights(db, user_id))
        except AppError as exc:
            log.warning("news_insights_failed", error=exc.code)


# ---- interactions --------------------------------------------------------------------------


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
    await interests.touch(user_id)


async def unsave(db: AsyncSession, user_id: uuid.UUID, item_id: uuid.UUID) -> None:
    await _ensure_item(db, item_id)
    await db.execute(
        delete(SavedNews).where(SavedNews.user_id == user_id, SavedNews.news_item_id == item_id)
    )
    await db.commit()
    await invalidate_dashboard(user_id)
    await interests.touch(user_id)


async def interact(
    db: AsyncSession, user_id: uuid.UUID, item_id: uuid.UUID, kind: InteractionKind, on: bool
) -> None:
    await _ensure_item(db, item_id)
    if on:
        await db.execute(
            insert(NewsInteraction)
            .values(id=uuid.uuid4(), user_id=user_id, news_item_id=item_id, kind=kind)
            .on_conflict_do_nothing(index_elements=["user_id", "news_item_id", "kind"])
        )
    else:
        await db.execute(
            delete(NewsInteraction).where(
                NewsInteraction.user_id == user_id,
                NewsInteraction.news_item_id == item_id,
                NewsInteraction.kind == kind,
            )
        )
    await db.commit()
    await interests.touch(user_id)


# ---- refresh -------------------------------------------------------------------------------


async def refresh(db: AsyncSession, provider: NewsProvider) -> int:
    """Pull from the provider and insert new URLs. Never raises for a failing source."""
    fetched = await provider.fetch()
    if not fetched:
        return 0
    unique: dict[str, FetchedNews] = {f.url: f for f in fetched}
    existing = set(await db.scalars(select(NewsItem.url).where(NewsItem.url.in_(list(unique)))))
    fresh = [f for f in unique.values() if f.url not in existing]
    # Votes and comments keep climbing on HN, Reddit, DEV: update the ones we already have.
    for f in unique.values():
        if f.url in existing and (f.score or f.comments):
            await db.execute(
                update(NewsItem)
                .where(NewsItem.url == f.url)
                .values(score=f.score, comments=f.comments)
            )
    images: dict[str, str] = {}
    enrich = getattr(provider, "preview_images", None)
    if enrich is not None:
        try:
            images = await enrich([f.url for f in fresh if not f.image_url])
        except Exception as exc:
            log.warning("news_images_failed", error=type(exc).__name__)
    rows = [
        {
            "id": uuid.uuid4(),
            "title": f.title,
            "source": f.source,
            "url": f.url,
            "summary": f.summary,
            "image_url": f.image_url or images.get(f.url),
            "category": f.category,
            "published_at": f.published_at,
            "kind": f.kind,
            "score": f.score,
            "comments": f.comments,
            "discussion_url": f.discussion_url,
            "author": f.author,
            "tags": list(f.tags),
        }
        for f in fresh
    ]
    added = 0
    if rows:
        result = await db.scalars(
            insert(NewsItem)
            .values(rows)
            .on_conflict_do_nothing(index_elements=["url"])
            .returning(NewsItem.id)
        )
        added = len(result.all())
    # Keep the table small: old stories nobody saved go away.
    cutoff = datetime.now(UTC) - timedelta(days=RETENTION_DAYS)
    await db.execute(
        delete(NewsItem).where(
            NewsItem.published_at < cutoff,
            ~NewsItem.id.in_(select(SavedNews.news_item_id)),
        )
    )
    await db.commit()
    await bump_version(NEWS_SCOPE)
    return added


async def run_refresh(provider: NewsProvider) -> None:
    """Background job with its own session (the request's session is closed by then)."""
    from app.db.session import SessionLocal
    from app.shared.refresh import release

    async with SessionLocal() as db:
        try:
            added = await asyncio.wait_for(refresh(db, provider), timeout=150)
            log.info("news_refreshed", added=added)
        except Exception as exc:
            log.warning("news_refresh_failed", error=type(exc).__name__)
            await release("news")
