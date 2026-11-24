"""Job discovery: pull public job boards, rank openings for the user, let the AI judge the fit."""

import asyncio
import math
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ai import AIClient
from app.core.exceptions import AppError, NotFoundError
from app.core.logging import get_logger
from app.core.redis import bump_version, cache_get, cache_set, cache_version, get_redis
from app.features.auth.models import User
from app.features.discover.models import JobMatch, JobPosting, MatchStatus
from app.features.discover.providers import JobsProvider
from app.features.discover.schemas import DiscoverPage, JobFit, PostingOut
from app.features.jobs import service as jobs_service
from app.features.jobs.models import Job
from app.features.jobs.schemas import JobCreate
from app.features.personalize import service as interests
from app.features.personalize.models import SearchScope
from app.features.profile.models import Experience
from app.shared.pagination import Page, PageParams
from app.shared.text import normalise_tag, token_set

log = get_logger(__name__)

JOBS_SCOPE = "job_postings"
POOL_DAYS = 45
POOL_SIZE = 2000
ORDER_CACHE_SECONDS = 300
FIT_BATCH = 12
FIT_COOLDOWN_SECONDS = 900
RETENTION_DAYS = 60
_NON_ENGLISH_HINTS = ("(m/w/d", "(w/m/d", "(m/f/d", "(f/m/d", "m/w/d)", "mitarbeiter", "entwickler")


def _regions_wanted(region: str | None, prefs: list[str]) -> set[str] | None:
    """None means no filter."""
    if region:
        return None if region == "anywhere" else {region}
    if not prefs or "anywhere" in prefs:
        return None
    return set(prefs)


def _matches(posting: JobPosting, q: str) -> bool:
    hay = f"{posting.role} {posting.company} {posting.summary} {' '.join(posting.tags)}".lower()
    return all(part in hay for part in q.lower().split())


async def _order(
    db: AsyncSession, user_id: uuid.UUID, region: str | None, q: str | None
) -> list[tuple[uuid.UUID, int]]:
    """(posting id, match 0-100) best first; cached per user, filters and data version."""
    q = (q or "").strip()
    jobs_v = await cache_version(JOBS_SCOPE)
    me_v = await cache_version(interests.scope_key(user_id))
    key = f"cache:discover:{user_id}:j{jobs_v}:i{me_v}:{region or 'pref'}:{q.lower()}"
    cached = await cache_get(key)
    if cached is not None:
        return [(uuid.UUID(i), int(m)) for i, m in cached]

    profile = await interests.get_or_create(db, user_id)
    wanted = _regions_wanted(region, list(profile.job_regions or []))
    now = datetime.now(UTC)
    pool = await db.scalars(
        select(JobPosting)
        .where(JobPosting.posted_at >= now - timedelta(days=POOL_DAYS))
        .order_by(JobPosting.posted_at.desc())
        .limit(POOL_SIZE)
    )
    states = {
        m.posting_id: m
        for m in await db.scalars(select(JobMatch).where(JobMatch.user_id == user_id))
    }
    weights = await interests.terms(db, user_id)

    scored: list[tuple[float, uuid.UUID, int]] = []
    for p in pool:
        state = states.get(p.id)
        if state is not None and state.status == MatchStatus.HIDDEN:
            continue
        if wanted is not None and not (wanted & set(p.regions or [])):
            continue
        if q and not _matches(p, q):
            continue
        words = token_set(p.role, p.summary) | {normalise_tag(t) for t in p.tags or []}
        personal = interests.match(weights, words, p.role)
        if personal < 0:
            continue
        age_days = max(0.0, (now - p.posted_at).total_seconds() / 86400)
        # The role title carries most of the signal: count it twice.
        role_match = interests.match(weights, token_set(p.role), p.role)
        score = 0.35 * personal + 0.3 * max(role_match, 0) + 0.2 * math.exp(-age_days / 14)
        if state is not None and state.fit is not None:
            score += 0.45 * state.fit / 100
        if any(h in p.role.lower() for h in _NON_ENGLISH_HINTS):
            score -= 0.2
        scored.append((score, p.id, round(100 * max(personal, role_match))))
    scored.sort(key=lambda s: s[0], reverse=True)
    order = [(pid, m) for _, pid, m in scored]
    await cache_set(key, [[str(i), m] for i, m in order], ORDER_CACHE_SECONDS)
    return order


async def _decorate(
    db: AsyncSession, user_id: uuid.UUID, postings: list[JobPosting], scores: dict[uuid.UUID, int]
) -> list[PostingOut]:
    ids = [p.id for p in postings]
    states = (
        {
            m.posting_id: m
            for m in await db.scalars(
                select(JobMatch).where(JobMatch.user_id == user_id, JobMatch.posting_id.in_(ids))
            )
        }
        if ids
        else {}
    )
    out = []
    for p in postings:
        item = PostingOut.model_validate(p)
        item.match_score = scores.get(p.id, 0)
        state = states.get(p.id)
        if state is not None:
            item.status = state.status
            item.job_id = state.job_id
            if state.fit is not None:
                item.fit = JobFit(fit=state.fit, reason=state.reason, gaps=state.gaps)
        out.append(item)
    return out


async def discover(
    db: AsyncSession,
    user_id: uuid.UUID,
    params: PageParams,
    region: str | None = None,
    q: str | None = None,
    personalizing: bool = False,
) -> DiscoverPage:
    if q and params.page == 1:
        await interests.record_search(db, user_id, SearchScope.JOBS, q)
    order = await _order(db, user_id, region, q)
    page = order[params.offset : params.offset + params.size]
    ids = [pid for pid, _ in page]
    rows = {p.id: p for p in await db.scalars(select(JobPosting).where(JobPosting.id.in_(ids)))}
    items = await _decorate(db, user_id, [rows[i] for i in ids if i in rows], dict(page))
    base = Page[PostingOut].build(items, len(order), params)
    return DiscoverPage(
        **base.model_dump(exclude={"items"}), items=items, personalizing=personalizing
    )


# ---- AI fit --------------------------------------------------------------------------------


async def needs_fit(
    db: AsyncSession, user_id: uuid.UUID, region: str | None = None
) -> list[uuid.UUID]:
    head = [pid for pid, _ in (await _order(db, user_id, region, None))[: FIT_BATCH * 2]]
    if not head:
        return []
    rated = set(
        await db.scalars(
            select(JobMatch.posting_id).where(
                JobMatch.user_id == user_id,
                JobMatch.posting_id.in_(head),
                JobMatch.fit.is_not(None),
            )
        )
    )
    return [i for i in head if i not in rated][:FIT_BATCH]


class RatedJob(BaseModel):
    n: int = Field(description="The number of the job in the list")
    fit: int = Field(description="0-100: how well the candidate fits this job")
    reason: str = Field(description="At most 25 words: why it fits, to the candidate ('you')")
    gaps: str = Field(description="At most 20 words: what's missing or risky; empty if nothing")


class RatedJobs(BaseModel):
    items: list[RatedJob]


FIT_SYSTEM = """You are a sharp, honest career coach screening job openings for one candidate.
For every numbered job, score fit 0-100 from the candidate's skills, experience, target roles and
interests (60+ means worth applying). Consider seniority and location: the candidate lives where
the context says; a job restricted to another country they can't work in scores under 30.
`reason`: why it fits, concrete (skills, domain), addressed to the candidate as "you".
`gaps`: the main missing skill or risk, or an empty string. Never invent requirements that are
not in the job text."""


async def _candidate(db: AsyncSession, user: User) -> str:
    ctx = await interests.context(db, user)
    exp = await db.scalars(
        select(Experience)
        .where(Experience.user_id == user.id)
        .order_by(Experience.start_date.desc())
        .limit(6)
    )
    lines = [
        f"- {e.title} at {e.company} ({e.start_date:%Y}-{'now' if e.current else e.end_date})"
        for e in exp
    ]
    return ctx + ("\nExperience:\n" + "\n".join(lines) if lines else "")


async def write_fits(db: AsyncSession, user: User, ai: AIClient, ids: list[uuid.UUID]) -> int:
    if not ids:
        return 0
    found = {p.id: p for p in await db.scalars(select(JobPosting).where(JobPosting.id.in_(ids)))}
    postings = [found[i] for i in ids if i in found]
    if not postings:
        return 0
    listing = "\n".join(
        f"{n}. {p.role} at {p.company} — location: {p.location or 'n/a'}"
        f"{' (remote)' if p.remote else ''}; tags: {', '.join(p.tags[:8]) or '-'}\n"
        f"   {p.summary[:450]}"
        for n, p in enumerate(postings, start=1)
    )
    result = await ai.generate_structured(
        system=FIT_SYSTEM,
        prompt=f"Candidate:\n{await _candidate(db, user)}\n\nJobs:\n{listing}",
        schema=RatedJobs,
    )
    by_n = {r.n: r for r in result.items}
    rows = [
        {
            "id": uuid.uuid4(),
            "user_id": user.id,
            "posting_id": p.id,
            "fit": max(0, min(100, by_n[n].fit)),
            "reason": by_n[n].reason.strip()[:400],
            "gaps": by_n[n].gaps.strip()[:400],
        }
        for n, p in enumerate(postings, start=1)
        if n in by_n
    ]
    if rows:
        stmt = insert(JobMatch).values(rows)
        await db.execute(
            stmt.on_conflict_do_update(
                index_elements=["user_id", "posting_id"],
                set_={
                    "fit": stmt.excluded.fit,
                    "reason": stmt.excluded.reason,
                    "gaps": stmt.excluded.gaps,
                },
            )
        )
        await db.commit()
        await interests.touch(user.id)
    return len(rows)


async def claim_fit_run(user_id: uuid.UUID) -> bool:
    try:
        return bool(
            await get_redis().set(f"lock:fit:{user_id}", "1", ex=FIT_COOLDOWN_SECONDS, nx=True)
        )
    except Exception:
        return False


async def run_fits(user_id: uuid.UUID, ai: AIClient, region: str | None) -> None:
    from app.db.session import SessionLocal

    async with SessionLocal() as db:
        user = await db.get(User, user_id)
        if user is None:
            return
        try:
            await write_fits(db, user, ai, await needs_fit(db, user_id, region))
        except AppError as exc:
            log.warning("job_fit_failed", error=exc.code)


# ---- actions -------------------------------------------------------------------------------


async def _posting(db: AsyncSession, posting_id: uuid.UUID) -> JobPosting:
    posting = await db.get(JobPosting, posting_id)
    if posting is None:
        raise NotFoundError("Job posting not found", code="POSTING_NOT_FOUND")
    return posting


async def _state(db: AsyncSession, user_id: uuid.UUID, posting_id: uuid.UUID) -> JobMatch:
    state = await db.scalar(
        select(JobMatch).where(JobMatch.user_id == user_id, JobMatch.posting_id == posting_id)
    )
    if state is None:
        state = JobMatch(user_id=user_id, posting_id=posting_id, status=MatchStatus.NEW)
        db.add(state)
        await db.flush()
    return state


async def set_hidden(
    db: AsyncSession, user_id: uuid.UUID, posting_id: uuid.UUID, hidden: bool
) -> None:
    await _posting(db, posting_id)
    state = await _state(db, user_id, posting_id)
    if state.status != MatchStatus.TRACKED:
        state.status = MatchStatus.HIDDEN if hidden else MatchStatus.NEW
    await db.commit()
    await interests.touch(user_id)


async def track(db: AsyncSession, user_id: uuid.UUID, posting_id: uuid.UUID) -> Job:
    """Copy the posting into the job tracker (as saved). Tracking twice returns the same job."""
    posting = await _posting(db, posting_id)
    state = await _state(db, user_id, posting_id)
    if state.job_id is not None:
        job = await db.get(Job, state.job_id)
        if job is not None and job.user_id == user_id:
            return job
    notes = [f"Found on {posting.source}."]
    if state.fit is not None:
        notes.append(f"AI fit {state.fit}/100: {state.reason}")
        if state.gaps:
            notes.append(f"Gaps: {state.gaps}")
    if posting.salary:
        notes.append(f"Salary: {posting.salary}")
    job = await jobs_service.create_job(
        db,
        user_id,
        JobCreate(
            company=posting.company[:200],
            role=posting.role[:200],
            location=(posting.location or ("Remote" if posting.remote else None) or "")[:120]
            or None,
            url=posting.url,
            notes="\n".join(notes),
            tags=[t[:50] for t in posting.tags[:20]],
            currency="USD" if (posting.salary or "").startswith(("$", "USD")) else "INR",
        ),
    )
    state = await _state(db, user_id, posting_id)
    state.status = MatchStatus.TRACKED
    state.job_id = job.id
    await db.commit()
    await interests.touch(user_id)
    return job


# ---- refresh -------------------------------------------------------------------------------


async def refresh(db: AsyncSession, provider: JobsProvider) -> int:
    fetched = await provider.fetch()
    if not fetched:
        return 0
    unique = {f.url: f for f in fetched if f.role}
    rows: list[dict[str, Any]] = [
        {
            "id": uuid.uuid4(),
            "source": f.source,
            "url": f.url,
            "company": f.company,
            "role": f.role,
            "location": f.location,
            "remote": f.remote,
            "regions": list(f.regions),
            "tags": list(f.tags),
            "salary": f.salary,
            "employment_type": f.employment_type,
            "summary": f.summary,
            "logo_url": f.logo_url,
            "posted_at": f.posted_at,
        }
        for f in unique.values()
    ]
    added = 0
    for start in range(0, len(rows), 500):  # keep statements under the bind-parameter limit
        result = await db.scalars(
            insert(JobPosting)
            .values(rows[start : start + 500])
            .on_conflict_do_nothing(index_elements=["url"])
            .returning(JobPosting.id)
        )
        added += len(result.all())
    cutoff = datetime.now(UTC) - timedelta(days=RETENTION_DAYS)
    await db.execute(delete(JobPosting).where(JobPosting.posted_at < cutoff))
    await db.commit()
    await bump_version(JOBS_SCOPE)
    return added


async def run_refresh(provider: JobsProvider) -> None:
    from app.db.session import SessionLocal
    from app.shared.refresh import release

    async with SessionLocal() as db:
        try:
            added = await asyncio.wait_for(refresh(db, provider), timeout=150)
            log.info("job_postings_refreshed", added=added)
        except Exception as exc:
            log.warning("job_postings_refresh_failed", error=type(exc).__name__)
            await release("jobs")
