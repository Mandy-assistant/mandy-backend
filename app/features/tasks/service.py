"""Study tasks. Date filters use the caller's timezone."""

import uuid
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Select, case, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationFailed
from app.features.dashboard.cache import invalidate_dashboard
from app.features.roadmaps.models import Milestone, Roadmap
from app.features.tasks.models import Task, TaskPriority, TaskStatus
from app.features.tasks.schemas import TaskCreate, TaskFilter, TaskUpdate
from app.shared.timeutil import local_today

PRIORITY_RANK = case(
    {TaskPriority.HIGH.value: 0, TaskPriority.MEDIUM.value: 1, TaskPriority.LOW.value: 2},
    value=Task.priority,
)
NON_NULLABLE = {"title", "priority"}


async def get_task(db: AsyncSession, task_id: uuid.UUID, user_id: uuid.UUID) -> Task:
    task = await db.scalar(
        select(Task)
        .where(Task.id == task_id, Task.user_id == user_id)
        .execution_options(populate_existing=True)
    )
    if task is None:
        raise NotFoundError("Task not found", code="TASK_NOT_FOUND")
    return task


def apply_filter(stmt: Select[Any], flt: TaskFilter | None, tz: ZoneInfo) -> Select[Any]:
    today = local_today(tz)
    open_ = Task.status == TaskStatus.TODO
    if flt == "today":
        return stmt.where(open_, Task.due_date == today)
    if flt == "upcoming":
        return stmt.where(open_, Task.due_date > today)
    if flt == "overdue":
        return stmt.where(open_, Task.due_date < today)
    if flt == "completed":
        return stmt.where(Task.status == TaskStatus.DONE)
    return stmt


async def list_tasks(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    flt: TaskFilter | None = None,
    priority: TaskPriority | None = None,
    roadmap_id: uuid.UUID | None = None,
    milestone_id: uuid.UUID | None = None,
    tz: ZoneInfo = ZoneInfo("UTC"),
) -> list[Task]:
    stmt = apply_filter(select(Task).where(Task.user_id == user_id), flt, tz)
    if priority is not None:
        stmt = stmt.where(Task.priority == priority)
    if roadmap_id is not None:
        stmt = stmt.where(Task.roadmap_id == roadmap_id)
    if milestone_id is not None:
        stmt = stmt.where(Task.milestone_id == milestone_id)
    if flt == "completed":
        stmt = stmt.order_by(Task.completed_at.desc().nulls_last(), Task.id)
    else:
        status_rank = case({"todo": 0, "done": 1}, value=Task.status)
        stmt = stmt.order_by(
            status_rank, Task.due_date.asc().nulls_last(), PRIORITY_RANK, Task.created_at
        )
    return list((await db.scalars(stmt)).unique())


async def _validate_links(
    db: AsyncSession,
    user_id: uuid.UUID,
    roadmap_id: uuid.UUID | None,
    milestone_id: uuid.UUID | None,
) -> uuid.UUID | None:
    """Both must belong to the user (else 404); returns the effective roadmap id."""
    if roadmap_id is not None:
        owned = await db.scalar(
            select(Roadmap.id).where(Roadmap.id == roadmap_id, Roadmap.user_id == user_id)
        )
        if owned is None:
            raise NotFoundError("Roadmap not found", code="ROADMAP_NOT_FOUND")
    if milestone_id is not None:
        ms_roadmap = await db.scalar(
            select(Milestone.roadmap_id)
            .join(Roadmap, Roadmap.id == Milestone.roadmap_id)
            .where(Milestone.id == milestone_id, Roadmap.user_id == user_id)
        )
        if ms_roadmap is None:
            raise NotFoundError("Milestone not found", code="MILESTONE_NOT_FOUND")
        if roadmap_id is not None and ms_roadmap != roadmap_id:
            raise ValidationFailed("milestone_id", "Milestone belongs to a different roadmap")
        return ms_roadmap
    return roadmap_id


async def create_task(db: AsyncSession, user_id: uuid.UUID, data: TaskCreate) -> Task:
    roadmap_id = await _validate_links(db, user_id, data.roadmap_id, data.milestone_id)
    task = Task(user_id=user_id, **data.model_dump(exclude={"roadmap_id"}), roadmap_id=roadmap_id)
    db.add(task)
    await db.commit()
    await invalidate_dashboard(user_id)
    return await get_task(db, task.id, user_id)


async def update_task(
    db: AsyncSession, task_id: uuid.UUID, user_id: uuid.UUID, data: TaskUpdate
) -> Task:
    task = await get_task(db, task_id, user_id)
    changes = data.model_dump(exclude_unset=True)
    if "roadmap_id" in changes or "milestone_id" in changes:
        roadmap_id = changes.get("roadmap_id", task.roadmap_id)
        milestone_id = changes.get("milestone_id", task.milestone_id)
        if "roadmap_id" in changes and "milestone_id" not in changes and milestone_id:
            # moving to another roadmap (or none) detaches the old milestone
            ms_roadmap = await db.scalar(
                select(Milestone.roadmap_id).where(Milestone.id == milestone_id)
            )
            if ms_roadmap != roadmap_id:
                milestone_id = None
        changes["roadmap_id"] = await _validate_links(db, user_id, roadmap_id, milestone_id)
        changes["milestone_id"] = milestone_id
    for key, value in changes.items():
        if value is None and key in NON_NULLABLE:
            continue
        setattr(task, key, value)
    await db.commit()
    await invalidate_dashboard(user_id)
    return await get_task(db, task.id, user_id)


async def set_done(db: AsyncSession, task_id: uuid.UUID, user_id: uuid.UUID, done: bool) -> Task:
    task = await get_task(db, task_id, user_id)
    if done and task.status != TaskStatus.DONE:
        task.status = TaskStatus.DONE
        task.completed_at = datetime.now(UTC)
    elif not done:
        task.status = TaskStatus.TODO
        task.completed_at = None
    await db.commit()
    await invalidate_dashboard(user_id)
    return await get_task(db, task.id, user_id)


async def delete_task(db: AsyncSession, task_id: uuid.UUID, user_id: uuid.UUID) -> None:
    task = await get_task(db, task_id, user_id)
    await db.delete(task)
    await db.commit()
    await invalidate_dashboard(user_id)
