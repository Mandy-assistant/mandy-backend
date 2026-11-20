"""Demo data for local development.

    uv run python -m app.scripts.seed            # create demo data if missing
    uv run python -m app.scripts.seed --reset    # wipe the owner's data and recreate it

Creates the single owner (Mathan, demo@mandy.dev) **without a passkey** — `/auth/setup/*` then
attaches the first passkey to this user. Every date is relative to today (Asia/Kolkata), so the
dashboard always looks fresh. Idempotent: running it repeatedly never duplicates anything.
"""

import argparse
import asyncio
import random
import re
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import bump_version
from app.features.auth.models import User
from app.features.auth.service import DEFAULT_OWNER_EMAIL, DEFAULT_OWNER_NAME, get_owner
from app.features.dashboard.cache import invalidate_dashboard
from app.features.focus.models import FocusSession
from app.features.jobs.models import Job, JobStatus, JobStatusEvent
from app.features.news.models import NewsItem, SavedNews
from app.features.news.service import NEWS_SCOPE
from app.features.profile.models import (
    Education,
    Experience,
    Profile,
    Skill,
    SkillCategory,
    SkillLevel,
)
from app.features.resumes import service as resume_service
from app.features.resumes.models import Resume, ResumeTemplate, ResumeVersion
from app.features.resumes.schemas import ResumeContent, SectionItem
from app.features.roadmaps.models import Milestone, MilestoneStatus, Roadmap, RoadmapStatus
from app.features.tasks.models import Task, TaskPriority, TaskStatus
from app.scripts import seed_data as data

SEED_TZ = ZoneInfo("Asia/Kolkata")
PIPELINE_ORDER = [JobStatus.SAVED, JobStatus.APPLIED, JobStatus.INTERVIEW, JobStatus.OFFER]


def local_dt(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=SEED_TZ).astimezone(UTC)


def _date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:80]


async def get_or_create_owner(db: AsyncSession) -> User:
    owner = await get_owner(db)
    if owner is None:
        owner = User(email=DEFAULT_OWNER_EMAIL, display_name=DEFAULT_OWNER_NAME)
        db.add(owner)
        await db.flush()
    return owner


async def wipe_user_data(db: AsyncSession, user: User) -> None:
    """Delete everything the owner created, but keep the user, passkeys and recovery codes."""
    uid = user.id
    for model in (
        FocusSession,
        Task,
        Job,
        Resume,
        Roadmap,
        Experience,
        Education,
        Skill,
        Profile,
        SavedNews,
    ):
        await db.execute(delete(model).where(model.user_id == uid))


async def seed_profile(db: AsyncSession, user: User) -> None:
    db.add(Profile(user_id=user.id, **data.PROFILE))
    for exp in data.EXPERIENCE:
        db.add(
            Experience(
                user_id=user.id,
                **{
                    **exp,
                    "start_date": _date(exp["start_date"]),
                    "end_date": _date(exp["end_date"]),
                },
            )
        )
    for edu in data.EDUCATION:
        db.add(
            Education(
                user_id=user.id,
                **{
                    **edu,
                    "start_date": _date(edu["start_date"]),
                    "end_date": _date(edu["end_date"]),
                },
            )
        )
    for name, level, category in data.SKILLS:
        db.add(
            Skill(
                user_id=user.id,
                name=name,
                level=SkillLevel(level),
                category=SkillCategory(category),
            )
        )
    await db.flush()


async def seed_resumes(db: AsyncSession, user: User) -> None:
    fe = await resume_service.build_content_from_profile(db, user)
    fe.header.headline = "Senior Frontend Engineer"
    await _resume(db, user, "Frontend Engineer — 2026", ResumeTemplate.MODERN, fe, versions=2)

    ml = await resume_service.build_content_from_profile(db, user)
    ml.header.headline = "ML Engineer (transitioning from frontend)"
    for section in ml.sections:
        if section.type == "summary":
            section.text = (
                "Engineer moving from frontend into ML: 5 years shipping production web apps, "
                "plus hands-on PyTorch and scikit-learn projects. I like owning models end to "
                "end — data, training, evaluation and the product surface."
            )
        if section.type == "projects":
            section.visible = True
            section.items = [
                SectionItem(
                    title="Tamil sentiment classifier",
                    subtitle="PyTorch, FastAPI",
                    description="Fine-tuned IndicBERT; served behind a FastAPI endpoint.",
                    bullets=["F1 0.87 on a held-out set", "p95 latency 40 ms on CPU"],
                    tags=["pytorch", "nlp"],
                    url="https://github.com/mathan-dev/tamil-sentiment",
                ),
                SectionItem(
                    title="House price predictor",
                    subtitle="scikit-learn",
                    bullets=["Top 12% on the Kaggle leaderboard"],
                    tags=["sklearn"],
                ),
            ]
    await _resume(db, user, "ML Engineer — 2026", ResumeTemplate.CLASSIC, ml, versions=1)


async def _resume(
    db: AsyncSession,
    user: User,
    title: str,
    template: ResumeTemplate,
    content: ResumeContent,
    versions: int,
) -> None:
    dumped = content.model_dump(mode="json")
    resume = Resume(
        user_id=user.id, title=title, template=template, content=dumped, current_version=versions
    )
    db.add(resume)
    await db.flush()
    for v in range(1, versions + 1):
        db.add(ResumeVersion(resume_id=resume.id, version=v, content=dumped))


async def seed_jobs(db: AsyncSession, user: User, today: date) -> None:
    friday = today + timedelta(days=(4 - today.weekday()) % 7)
    next_tuesday = today + timedelta(days=(1 - today.weekday()) % 7 or 7)
    interviews = {
        "Vercel": local_dt(friday, 11),
        "Flipkart": local_dt(next_tuesday, 15),
        "CRED": local_dt(today - timedelta(days=3), 14, 30),
    }
    positions: dict[JobStatus, int] = {}
    for company, role, location, status_value, applied_ago, extra in data.JOBS:
        status = JobStatus(status_value)
        applied_at = today - timedelta(days=applied_ago) if applied_ago is not None else None
        position = positions.get(status, 0)
        positions[status] = position + 1
        job = Job(
            user_id=user.id,
            company=company,
            role=role,
            location=location,
            status=status,
            applied_at=applied_at,
            interview_at=interviews.get(company),
            position=position,
            currency="INR",
            **extra,
        )
        created = local_dt((applied_at or today) - timedelta(days=2), 10)
        job.created_at = created
        db.add(job)
        await db.flush()
        # status history: saved → applied → interview → offer (or → rejected)
        path = [JobStatus.SAVED]
        if status != JobStatus.SAVED:
            path.append(JobStatus.APPLIED)
        if status in (JobStatus.INTERVIEW, JobStatus.OFFER):
            path.append(JobStatus.INTERVIEW)
        if status in (JobStatus.OFFER, JobStatus.REJECTED):
            path.append(status)
        prev: JobStatus | None = None
        for i, step in enumerate(path):
            when = created + timedelta(days=2 + 4 * i) if i else created
            db.add(
                JobStatusEvent(
                    job_id=job.id,
                    from_status=prev,
                    to_status=step,
                    changed_at=min(when, datetime.now(UTC)),
                )
            )
            prev = step
        job.updated_at = min(created + timedelta(days=2 + 4 * (len(path) - 1)), datetime.now(UTC))


async def seed_roadmaps(
    db: AsyncSession, user: User, today: date
) -> dict[str, tuple[Roadmap, list[Milestone]]]:
    out: dict[str, tuple[Roadmap, list[Milestone]]] = {}
    now = datetime.now(UTC)
    for i, spec in enumerate(data.ROADMAPS):
        roadmap = Roadmap(
            user_id=user.id,
            title=spec["title"],
            goal=spec["goal"],
            status=RoadmapStatus(spec["status"]),
            target_date=today + timedelta(days=spec["target_days"]),
        )
        # the last one (ML Engineer) is the most recently touched → dashboard "current roadmap"
        roadmap.created_at = now - timedelta(days=90 - 10 * i)
        roadmap.updated_at = now - timedelta(hours=len(data.ROADMAPS) - i)
        db.add(roadmap)
        await db.flush()
        milestones = []
        for pos, (title, status, due, resources) in enumerate(spec["milestones"]):
            m = Milestone(
                roadmap_id=roadmap.id,
                title=title,
                position=pos,
                status=MilestoneStatus(status),
                target_date=today + timedelta(days=due),
                description=f"Milestone {pos + 1} of {spec['title']}: {title.lower()}.",
                resources=[{"title": t, "url": u} for t, u in resources],
            )
            db.add(m)
            milestones.append(m)
        await db.flush()
        out[str(spec["key"])] = (roadmap, milestones)
    return out


async def seed_tasks(
    db: AsyncSession,
    user: User,
    today: date,
    roadmaps: dict[str, tuple[Roadmap, list[Milestone]]],
) -> dict[str, Task]:
    tasks: dict[str, Task] = {}
    now = datetime.now(UTC)
    for title, key, m_index, priority, due, completed_ago in data.TASKS:
        roadmap, milestones = roadmaps[key] if key else (None, [])
        task = Task(
            user_id=user.id,
            title=title,
            priority=TaskPriority(priority),
            due_date=today + timedelta(days=due) if due is not None else None,
            roadmap_id=roadmap.id if roadmap else None,
            milestone_id=milestones[m_index].id if roadmap and m_index is not None else None,
            status=TaskStatus.DONE if completed_ago is not None else TaskStatus.TODO,
        )
        if completed_ago is not None:
            done_at = local_dt(today - timedelta(days=completed_ago), 19, 15)
            if completed_ago == 0:
                done_at = min(local_dt(today, 8, 0), now - timedelta(minutes=5))
            task.completed_at = done_at
        db.add(task)
        tasks[title] = task
    await db.flush()
    return tasks


async def seed_focus(db: AsyncSession, user: User, today: date, tasks: dict[str, Task]) -> None:
    rng = random.Random(today.toordinal())  # deterministic for a given day
    now = datetime.now(UTC)
    linked = [
        tasks["Implement a CNN on CIFAR-10"],
        tasks["Solve 3 sliding-window problems"],
        tasks["Read 'Attention Is All You Need'"],
        tasks["Finish backprop derivation notes"],
    ]
    slots = [(7, 0), (9, 30), (14, 0), (18, 30), (21, 0)]
    durations = [25, 25, 45, 50, 60]
    for days_ago in range(104, -1, -1):
        if days_ago in (12, 39, 61):
            continue  # breaks that bound the current (12) and best (21) streaks
        active = days_ago <= 11 or 40 <= days_ago <= 60 or rng.random() < 0.6
        if not active:
            continue
        day = today - timedelta(days=days_ago)
        for hour, minute in sorted(rng.sample(slots, rng.randint(1, 4))):
            minutes = rng.choice(durations)
            start = local_dt(day, hour, minute)
            end = start + timedelta(minutes=minutes)
            if end > now:
                continue
            db.add(
                FocusSession(
                    user_id=user.id,
                    duration_minutes=minutes,
                    started_at=start,
                    ended_at=end,
                    task_id=rng.choice(linked).id if days_ago < 14 else None,
                )
            )
    # make sure today has at least one finished session so the streak is "live"
    early = local_dt(today, 0, 50)
    if now - timedelta(minutes=30) > early:
        has_today = await db.scalar(
            select(FocusSession.id)
            .where(FocusSession.user_id == user.id, FocusSession.started_at >= local_dt(today, 0))
            .limit(1)
        )
        if has_today is None:
            db.add(
                FocusSession(
                    user_id=user.id,
                    duration_minutes=25,
                    task_id=linked[0].id,
                    started_at=now - timedelta(minutes=30),
                    ended_at=now - timedelta(minutes=5),
                )
            )


async def seed_news(db: AsyncSession, now: datetime) -> int:
    rows: list[dict[str, Any]] = []
    for i, (category, source, domain, title, summary) in enumerate(data.NEWS):
        rows.append(
            {
                "title": title,
                "source": source,
                "summary": summary,
                "category": category,
                "url": f"https://{domain}/{_slug(title)}",
                "image_url": None,
                "published_at": now - timedelta(hours=5 + i * 5 + (i % 3)),
            }
        )
    stmt = insert(NewsItem).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["url"],
        set_={
            "title": stmt.excluded.title,
            "summary": stmt.excluded.summary,
            "published_at": stmt.excluded.published_at,
        },
    )
    await db.execute(stmt)
    return len(rows)


async def seed(
    db: AsyncSession, *, reset: bool = False, today: date | None = None
) -> dict[str, Any]:
    today = today or datetime.now(SEED_TZ).date()
    owner = await get_or_create_owner(db)
    news = await seed_news(db, datetime.now(UTC))
    existing = await db.scalar(select(Job.id).where(Job.user_id == owner.id).limit(1))
    if existing is not None and not reset:
        await db.commit()
        return {"owner": owner.email, "created": False, "news": news}
    await wipe_user_data(db, owner)
    await db.flush()
    await seed_profile(db, owner)
    await seed_resumes(db, owner)
    await seed_jobs(db, owner, today)
    roadmaps = await seed_roadmaps(db, owner, today)
    tasks = await seed_tasks(db, owner, today, roadmaps)
    await seed_focus(db, owner, today, tasks)
    saved = (
        await db.scalars(select(NewsItem.id).order_by(NewsItem.published_at.desc()).limit(4))
    ).all()
    for item_id in saved[1::2]:
        db.add(SavedNews(user_id=owner.id, news_item_id=item_id))
    await db.commit()
    await invalidate_dashboard(owner.id)
    await bump_version(NEWS_SCOPE)
    return {"owner": owner.email, "created": True, "news": news}


async def _main(reset: bool) -> None:
    from app.core.redis import close_redis
    from app.db.session import SessionLocal, engine

    try:
        async with SessionLocal() as db:
            result = await seed(db, reset=reset)
    finally:
        await close_redis()
        await engine.dispose()
    if result["created"]:
        print(f"Seeded demo data for {result['owner']} (+{result['news']} news items upserted).")
    else:
        print(
            f"Demo data already present for {result['owner']}; use --reset to recreate. "
            f"News refreshed ({result['news']} items)."
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed Mandy demo data")
    parser.add_argument("--reset", action="store_true", help="delete and recreate demo data")
    args = parser.parse_args()
    asyncio.run(_main(args.reset))


if __name__ == "__main__":
    main()
