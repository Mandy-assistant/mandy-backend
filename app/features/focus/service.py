"""Focus (pomodoro) sessions — feed the dashboard streak, heatmap and timeline."""

import uuid
from datetime import date
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.features.dashboard.cache import invalidate_dashboard
from app.features.focus.models import FocusSession
from app.features.focus.schemas import FocusSessionCreate
from app.features.tasks.models import Task
from app.shared.timeutil import day_bounds_utc, local_today


async def create_session(
    db: AsyncSession, user_id: uuid.UUID, data: FocusSessionCreate
) -> FocusSession:
    if data.task_id is not None:
        owned = await db.scalar(
            select(Task.id).where(Task.id == data.task_id, Task.user_id == user_id)
        )
        if owned is None:
            raise NotFoundError("Task not found", code="TASK_NOT_FOUND")
    session = FocusSession(user_id=user_id, **data.model_dump())
    db.add(session)
    await db.commit()
    await invalidate_dashboard(user_id)
    return session


async def list_sessions(
    db: AsyncSession, user_id: uuid.UUID, day: date | None, tz: ZoneInfo
) -> list[FocusSession]:
    start, end = day_bounds_utc(day or local_today(tz), tz)
    rows = await db.scalars(
        select(FocusSession)
        .where(
            FocusSession.user_id == user_id,
            FocusSession.started_at >= start,
            FocusSession.started_at < end,
        )
        .order_by(FocusSession.started_at)
    )
    return list(rows)
