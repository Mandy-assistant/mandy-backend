"""The interest profile: what the user cares about, learned from what they do.

Signals (strongest first): topics they follow, their skills and target roles, items they save,
like or open, what they search for, the jobs they track. Recent activity counts more (it decays
with a three-week half-life). Muted topics push matching items down hard.

`terms()` gives weights for ranking; `context()` turns the same data into plain text that every
AI prompt (news, job fit, resumes, chat) gets, so the AI knows who it is talking to.
"""

import math
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import bump_version, cache_get, cache_set, cache_version
from app.features.auth.models import User
from app.features.jobs.models import Job
from app.features.news.models import InteractionKind, NewsInteraction, NewsItem, SavedNews
from app.features.personalize.models import InterestProfile, SearchEvent, SearchScope
from app.features.profile.models import Profile, Skill, SkillLevel
from app.shared.text import normalise_tag, token_set, tokens

FOLLOW_WEIGHT = 3.0
MUTE_WEIGHT = -4.0
ROLE_WEIGHT = 2.0
HEADLINE_WEIGHT = 1.0
SKILL_WEIGHT = {SkillLevel.BEGINNER: 1.0, SkillLevel.INTERMEDIATE: 1.5, SkillLevel.ADVANCED: 2.0}
ACTIVITY_WEIGHT = {
    "save": 2.0,
    InteractionKind.LIKE: 1.5,
    InteractionKind.OPEN: 0.6,
    InteractionKind.HIDE: -0.8,
}
SEARCH_WEIGHT = 1.2
TRACKED_JOB_WEIGHT = 1.0
HALF_LIFE_DAYS = 21
MAX_TERMS = 80
ACTIVITY_WINDOW_DAYS = 90
TERMS_CACHE_SECONDS = 600
JOB_REGIONS = ("remote", "india", "anywhere")


def scope_key(user_id: uuid.UUID) -> str:
    return f"interests:{user_id}"


async def touch(user_id: uuid.UUID) -> None:
    """Something the profile depends on changed: rebuild on next use."""
    await bump_version(scope_key(user_id))


def _decay(when: datetime, now: datetime) -> float:
    age_days = max(0.0, (now - when).total_seconds() / 86400)
    return float(0.5 ** (age_days / HALF_LIFE_DAYS))


def _add(weights: dict[str, float], words: set[str] | list[str], amount: float) -> None:
    for w in words:
        weights[w] = weights.get(w, 0.0) + amount


async def get_or_create(db: AsyncSession, user_id: uuid.UUID) -> InterestProfile:
    row = await db.scalar(select(InterestProfile).where(InterestProfile.user_id == user_id))
    if row is None:
        row = InterestProfile(user_id=user_id, followed=[], muted=[], job_regions=[], learned={})
        db.add(row)
        await db.flush()
    return row


async def _build(db: AsyncSession, user_id: uuid.UUID) -> dict[str, float]:
    now = datetime.now(UTC)
    since = now - timedelta(days=ACTIVITY_WINDOW_DAYS)
    weights: dict[str, float] = {}

    interests = await get_or_create(db, user_id)
    for topic in interests.followed or []:
        weights[normalise_tag(topic)] = weights.get(normalise_tag(topic), 0.0) + FOLLOW_WEIGHT

    profile = await db.scalar(select(Profile).where(Profile.user_id == user_id))
    if profile is not None:
        for role in profile.target_roles or []:
            _add(weights, token_set(role), ROLE_WEIGHT)
        _add(weights, token_set(profile.headline), HEADLINE_WEIGHT)
    for skill in await db.scalars(select(Skill).where(Skill.user_id == user_id)):
        name = normalise_tag(skill.name)
        weights[name] = weights.get(name, 0.0) + SKILL_WEIGHT.get(skill.level, 1.5)

    # News activity: item words (title + tags) weighted by what was done and how long ago.
    activity = await db.execute(
        select(NewsInteraction.kind, NewsInteraction.created_at, NewsItem.title, NewsItem.tags)
        .join(NewsItem, NewsItem.id == NewsInteraction.news_item_id)
        .where(NewsInteraction.user_id == user_id, NewsInteraction.created_at >= since)
        .order_by(NewsInteraction.created_at.desc())
        .limit(400)
    )
    for kind, when, title, tags in activity:
        words = token_set(title) | {normalise_tag(t) for t in tags or []}
        _add(weights, words, ACTIVITY_WEIGHT[kind] * _decay(when, now))
    saved = await db.execute(
        select(SavedNews.created_at, NewsItem.title, NewsItem.tags)
        .join(NewsItem, NewsItem.id == SavedNews.news_item_id)
        .where(SavedNews.user_id == user_id, SavedNews.created_at >= since)
        .limit(200)
    )
    for when, title, tags in saved:
        words = token_set(title) | {normalise_tag(t) for t in tags or []}
        _add(weights, words, ACTIVITY_WEIGHT["save"] * _decay(when, now))

    searches = await db.execute(
        select(SearchEvent.query, SearchEvent.created_at)
        .where(SearchEvent.user_id == user_id, SearchEvent.created_at >= since)
        .order_by(SearchEvent.created_at.desc())
        .limit(100)
    )
    for query, when in searches:
        _add(weights, token_set(query), SEARCH_WEIGHT * _decay(when, now))

    jobs = await db.execute(
        select(Job.role, Job.tags, Job.updated_at)
        .where(Job.user_id == user_id)
        .order_by(Job.updated_at.desc())
        .limit(30)
    )
    for role, tags, when in jobs:
        words = token_set(role) | {normalise_tag(t) for t in tags or []}
        _add(weights, words, TRACKED_JOB_WEIGHT * _decay(when, now))

    for topic in interests.muted or []:
        weights[normalise_tag(topic)] = MUTE_WEIGHT

    positive = sorted(((w, t) for t, w in weights.items() if w > 0.05), reverse=True)[:MAX_TERMS]
    negative = [(w, t) for t, w in weights.items() if w < 0]
    return {t: round(w, 3) for w, t in positive + negative}


async def terms(db: AsyncSession, user_id: uuid.UUID) -> dict[str, float]:
    version = await cache_version(scope_key(user_id))
    key = f"cache:interests:{user_id}:v{version}"
    cached = await cache_get(key)
    if cached is not None:
        return {str(k): float(v) for k, v in dict(cached).items()}
    built = await _build(db, user_id)
    await cache_set(key, built, TERMS_CACHE_SECONDS)
    return built


def match(weights: dict[str, float], words: set[str], text: str = "") -> float:
    """How well a piece of content matches the profile: 0..1, or negative if it hits a mute."""
    if not weights:
        return 0.0
    lowered = text.lower()
    total = 0.0
    for term, weight in weights.items():
        hit = term in words or (" " in term and term in lowered)
        if hit:
            if weight < 0:
                return -1.0
            total += weight
    return 1 - math.exp(-total / 4)


async def record_search(
    db: AsyncSession, user_id: uuid.UUID, scope: SearchScope, query: str | None
) -> None:
    q = (query or "").strip()[:100]
    if len(q) < 2 or not tokens(q):
        return
    db.add(SearchEvent(user_id=user_id, scope=scope, query=q))
    await db.commit()
    await touch(user_id)


async def recent_searches(db: AsyncSession, user_id: uuid.UUID, limit: int = 8) -> list[str]:
    rows = await db.scalars(
        select(SearchEvent.query)
        .where(SearchEvent.user_id == user_id)
        .order_by(SearchEvent.created_at.desc())
        .limit(limit * 3)
    )
    return list(dict.fromkeys(q.lower() for q in rows))[:limit]


async def context(db: AsyncSession, user: User) -> str:
    """Plain-text description of the user for AI prompts (no secrets, no contact details)."""
    lines: list[str] = []
    interests = await get_or_create(db, user.id)
    profile = await db.scalar(select(Profile).where(Profile.user_id == user.id))
    if profile is not None:
        if profile.headline:
            lines.append(f"Headline: {profile.headline}")
        if profile.target_roles:
            lines.append(f"Target roles: {', '.join(profile.target_roles)}")
        if profile.location:
            lines.append(f"Based in: {profile.location}")
    skills = list(await db.scalars(select(Skill).where(Skill.user_id == user.id).limit(40)))
    if skills:
        lines.append("Skills: " + ", ".join(f"{s.name} ({s.level.value})" for s in skills))
    if interests.followed:
        lines.append(f"Follows topics: {', '.join(interests.followed)}")
    if interests.muted:
        lines.append(f"Not interested in: {', '.join(interests.muted)}")
    if interests.job_regions:
        lines.append(f"Job search regions: {', '.join(interests.job_regions)}")
    weights = await terms(db, user.id)
    top = [t for t, w in weights.items() if w > 0][:25]
    if top:
        lines.append(f"Strongest interests learned from activity: {', '.join(top)}")
    liked = await db.scalars(
        select(NewsItem.title)
        .join(NewsInteraction, NewsInteraction.news_item_id == NewsItem.id)
        .where(
            NewsInteraction.user_id == user.id,
            NewsInteraction.kind == InteractionKind.LIKE,
        )
        .order_by(NewsInteraction.created_at.desc())
        .limit(6)
    )
    liked_titles = list(liked)
    if liked_titles:
        lines.append("Recently liked stories: " + " | ".join(liked_titles))
    searches = await recent_searches(db, user.id)
    if searches:
        lines.append(f"Recent searches: {', '.join(searches)}")
    return "\n".join(lines) or "No profile or activity yet."


def as_list(weights: dict[str, float], limit: int = 30) -> list[dict[str, Any]]:
    return [
        {"term": t, "weight": w}
        for t, w in sorted(weights.items(), key=lambda kv: kv[1], reverse=True)[:limit]
    ]
