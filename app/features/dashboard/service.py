"""Dashboard summary: a handful of aggregate queries, cached per user for 60 s."""

from datetime import UTC, date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy import Date, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.redis import cache_get, cache_set
from app.features.auth.models import User
from app.features.dashboard.cache import dashboard_cache_key
from app.features.dashboard.schemas import (
    CurrentRoadmap,
    DashboardSummary,
    HeatmapDay,
    Pipeline,
    Streak,
    TimelineEntry,
)
from app.features.focus.models import FocusSession
from app.features.jobs.models import Job, JobStatus
from app.features.jobs.schemas import JobOut
from app.features.news import service as news_service
from app.features.roadmaps import service as roadmap_service
from app.features.roadmaps.models import MilestoneStatus, Roadmap, RoadmapStatus
from app.features.tasks.models import Task, TaskStatus
from app.features.tasks.schemas import TaskOut
from app.features.tasks.service import PRIORITY_RANK
from app.shared.timeutil import day_bounds_utc, local_today, week_start

HEATMAP_DAYS = 105
STREAK_WINDOW_DAYS = 365
ACTIVE_STATUSES = (JobStatus.APPLIED, JobStatus.INTERVIEW, JobStatus.OFFER)
PRACTICE_WORDS = ("dsa", "practice", "leetcode", "interview prep")


def _kind_for(roadmap_title: str | None) -> Literal["study", "practice"]:
    title = (roadmap_title or "").lower()
    return "practice" if any(w in title for w in PRACTICE_WORDS) else "study"


async def _pipeline(db: AsyncSession, user: User) -> Pipeline:
    rows = await db.execute(
        select(Job.status, func.count()).where(Job.user_id == user.id).group_by(Job.status)
    )
    return Pipeline(**{status.value: int(n) for status, n in rows.all()})


async def _activity_by_day(
    db: AsyncSession, user: User, tz: ZoneInfo, since: datetime
) -> dict[date, int]:
    tzname = tz.key
    focus_day = cast(func.timezone(tzname, FocusSession.started_at), Date)
    task_day = cast(func.timezone(tzname, Task.completed_at), Date)
    counts: dict[date, int] = {}
    focus_rows = await db.execute(
        select(focus_day, func.count())
        .where(FocusSession.user_id == user.id, FocusSession.started_at >= since)
        .group_by(focus_day)
    )
    task_rows = await db.execute(
        select(task_day, func.count())
        .where(Task.user_id == user.id, Task.completed_at.is_not(None), Task.completed_at >= since)
        .group_by(task_day)
    )
    for day, n in [*focus_rows.all(), *task_rows.all()]:
        counts[day] = counts.get(day, 0) + int(n)
    return counts


def compute_streak(counts: dict[date, int], today: date) -> tuple[int, int]:
    """Current streak counts back from today (or yesterday if today has no activity yet)."""
    current = 0
    day = today if counts.get(today) else today - timedelta(days=1)
    while counts.get(day):
        current += 1
        day -= timedelta(days=1)
    best = run = 0
    for offset in range(STREAK_WINDOW_DAYS, -1, -1):
        if counts.get(today - timedelta(days=offset)):
            run += 1
            best = max(best, run)
        else:
            run = 0
    return current, max(best, current)


async def _streak(db: AsyncSession, user: User, tz: ZoneInfo, today: date) -> Streak:
    since, _ = day_bounds_utc(today - timedelta(days=STREAK_WINDOW_DAYS), tz)
    counts = await _activity_by_day(db, user, tz, since)
    current, best = compute_streak(counts, today)
    week_from, _ = day_bounds_utc(week_start(today), tz)
    minutes = await db.scalar(
        select(func.coalesce(func.sum(FocusSession.duration_minutes), 0)).where(
            FocusSession.user_id == user.id, FocusSession.started_at >= week_from
        )
    )
    heatmap = [
        HeatmapDay(date=d, count=counts.get(d, 0))
        for d in (today - timedelta(days=i) for i in range(HEATMAP_DAYS - 1, -1, -1))
    ]
    return Streak(
        current_days=current, best_days=best, week_minutes=int(minutes or 0), heatmap=heatmap
    )


async def _current_roadmap(db: AsyncSession, user: User) -> CurrentRoadmap | None:
    roadmap = await db.scalar(
        select(Roadmap)
        .where(Roadmap.user_id == user.id, Roadmap.status == RoadmapStatus.ACTIVE)
        .order_by(Roadmap.updated_at.desc())
        .limit(1)
    )
    if roadmap is None:
        return None
    milestones = await roadmap_service.list_milestones(db, roadmap.id)
    total = len(milestones)
    done = sum(1 for m in milestones if m.status == MilestoneStatus.DONE)
    next_index = next(
        (i for i, m in enumerate(milestones) if m.status != MilestoneStatus.DONE), None
    )
    next_out = None
    if next_index is not None:
        next_out = (await roadmap_service.milestones_out(db, [milestones[next_index]]))[0]
    return CurrentRoadmap(
        id=roadmap.id,
        title=roadmap.title,
        progress=roadmap_service.progress_of(total, done),
        milestone_index=(next_index + 1) if next_index is not None else total,
        milestone_count=total,
        next_milestone=next_out,
    )


async def build_summary(db: AsyncSession, user: User, tz: ZoneInfo) -> DashboardSummary:
    now = datetime.now(UTC)
    today = local_today(tz)
    day_start, day_end = day_bounds_utc(today, tz)
    wk = week_start(today)
    wk_start, _ = day_bounds_utc(wk, tz)
    wk_end, _ = day_bounds_utc(wk + timedelta(days=7), tz)

    pipeline = await _pipeline(db, user)
    interviews_this_week = await db.scalar(
        select(func.count()).where(
            Job.user_id == user.id,
            Job.status != JobStatus.REJECTED,
            Job.interview_at >= wk_start,
            Job.interview_at < wk_end,
        )
    )
    next_interview = await db.scalar(
        select(Job)
        .where(
            Job.user_id == user.id,
            Job.status != JobStatus.REJECTED,
            Job.interview_at >= day_start,
        )
        .order_by(Job.interview_at)
        .limit(1)
    )

    open_task = (Task.user_id == user.id) & (Task.status == TaskStatus.TODO)
    due_today_q = select(Task).where(open_task, Task.due_date == today)
    tasks_due_today = list(
        (await db.scalars(due_today_q.order_by(PRIORITY_RANK, Task.created_at).limit(5))).unique()
    )
    due_today_count = await db.scalar(select(func.count()).where(open_task, Task.due_date == today))
    overdue_count = await db.scalar(select(func.count()).where(open_task, Task.due_date < today))
    completed_today = await db.scalar(
        select(func.count()).where(
            Task.user_id == user.id, Task.completed_at >= day_start, Task.completed_at < day_end
        )
    )
    focus_candidates = list(
        (
            await db.scalars(
                select(Task)
                .where(open_task, Task.due_date <= today)
                .order_by(PRIORITY_RANK, Task.due_date, Task.created_at)
                .limit(2)
            )
        ).unique()
    )
    focus_task = focus_candidates[0] if focus_candidates else None
    up_next = focus_candidates[1] if len(focus_candidates) > 1 else None
    if up_next is None:
        up_next = (
            await db.scalars(
                select(Task)
                .where(open_task, Task.due_date > today)
                .order_by(Task.due_date, PRIORITY_RANK)
                .limit(1)
            )
        ).first()

    # timeline: today's focus sessions, interviews today, tasks due today
    timeline: list[TimelineEntry] = []
    sessions = await db.execute(
        select(FocusSession, Task.title, Roadmap.title)
        .outerjoin(Task, Task.id == FocusSession.task_id)
        .outerjoin(Roadmap, Roadmap.id == Task.roadmap_id)
        .where(
            FocusSession.user_id == user.id,
            FocusSession.started_at >= day_start,
            FocusSession.started_at < day_end,
        )
        .order_by(FocusSession.started_at)
    )
    for session, task_title, roadmap_title in sessions.all():
        timeline.append(
            TimelineEntry(
                time=session.started_at.astimezone(tz).strftime("%H:%M"),
                title=task_title or f"Focus session · {session.duration_minutes} min",
                kind=_kind_for(roadmap_title),
                done=True,
            )
        )
    interviews = await db.scalars(
        select(Job)
        .where(
            Job.user_id == user.id,
            Job.status != JobStatus.REJECTED,
            Job.interview_at >= day_start,
            Job.interview_at < day_end,
        )
        .order_by(Job.interview_at)
    )
    for job in interviews:
        assert job.interview_at is not None
        timeline.append(
            TimelineEntry(
                time=job.interview_at.astimezone(tz).strftime("%H:%M"),
                title=f"{job.company} interview · {job.role}",
                kind="job",
                done=job.interview_at < now,
            )
        )
    todays_tasks = (
        await db.scalars(
            select(Task)
            .where(Task.user_id == user.id, Task.due_date == today)
            .order_by(PRIORITY_RANK, Task.created_at)
        )
    ).unique()
    for task in todays_tasks:
        timeline.append(
            TimelineEntry(
                time=None,
                title=task.title,
                kind=_kind_for(task.roadmap_title),
                done=task.status == TaskStatus.DONE,
            )
        )
    timeline.sort(key=lambda e: (e.time is None, e.time or ""))

    return DashboardSummary(
        owner_name=user.display_name,
        active_applications=sum(getattr(pipeline, s.value) for s in ACTIVE_STATUSES),
        interviews_this_week=int(interviews_this_week or 0),
        next_interview=JobOut.model_validate(next_interview) if next_interview else None,
        pipeline=pipeline,
        tasks_due_today=[TaskOut.model_validate(t) for t in tasks_due_today],
        tasks_due_today_count=int(due_today_count or 0),
        overdue_count=int(overdue_count or 0),
        completed_today=int(completed_today or 0),
        focus_task=TaskOut.model_validate(focus_task) if focus_task else None,
        up_next=TaskOut.model_validate(up_next) if up_next else None,
        current_roadmap=await _current_roadmap(db, user),
        latest_news=await news_service.latest(db, user.id, 3),
        streak=await _streak(db, user, tz, today),
        timeline=timeline,
    )


async def get_summary(db: AsyncSession, user: User, tz: ZoneInfo) -> DashboardSummary:
    key = await dashboard_cache_key(user.id, tz.key)
    cached = await cache_get(key)
    if cached is not None:
        return DashboardSummary.model_validate(cached)
    summary = await build_summary(db, user, tz)
    await cache_set(key, summary.model_dump(mode="json"), get_settings().dashboard_cache_seconds)
    return summary
