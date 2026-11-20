"""Roadmaps with ordered milestones; progress = done milestones / total."""

import uuid
from collections.abc import Iterable
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, NotFoundError
from app.db.base import utcnow
from app.features.dashboard.cache import invalidate_dashboard
from app.features.roadmaps.models import Milestone, MilestoneStatus, Roadmap
from app.features.roadmaps.schemas import (
    MilestoneCreate,
    MilestoneOut,
    MilestoneUpdate,
    RoadmapCreate,
    RoadmapDetail,
    RoadmapOut,
    RoadmapUpdate,
)
from app.features.tasks.models import Task, TaskStatus
from app.shared.ownership import get_owned_or_404

NON_NULLABLE = {"title", "resources", "status"}


def progress_of(total: int, done: int) -> int:
    return round(done * 100 / total) if total else 0


async def get_roadmap(db: AsyncSession, roadmap_id: uuid.UUID, user_id: uuid.UUID) -> Roadmap:
    return await get_owned_or_404(
        db, Roadmap, roadmap_id, user_id, code="ROADMAP_NOT_FOUND", message="Roadmap not found"
    )


async def get_milestone(db: AsyncSession, milestone_id: uuid.UUID, user_id: uuid.UUID) -> Milestone:
    milestone = await db.scalar(
        select(Milestone)
        .join(Roadmap, Roadmap.id == Milestone.roadmap_id)
        .where(Milestone.id == milestone_id, Roadmap.user_id == user_id)
        .execution_options(populate_existing=True)
    )
    if milestone is None:
        raise NotFoundError("Milestone not found", code="MILESTONE_NOT_FOUND")
    return milestone


async def milestone_stats(
    db: AsyncSession, roadmap_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, tuple[int, int]]:
    ids = list(roadmap_ids)
    if not ids:
        return {}
    rows = await db.execute(
        select(
            Milestone.roadmap_id,
            func.count(),
            func.count().filter(Milestone.status == MilestoneStatus.DONE),
        )
        .where(Milestone.roadmap_id.in_(ids))
        .group_by(Milestone.roadmap_id)
    )
    return {rid: (int(total), int(done)) for rid, total, done in rows.all()}


async def task_stats(
    db: AsyncSession, milestone_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, tuple[int, int]]:
    ids = list(milestone_ids)
    if not ids:
        return {}
    rows = await db.execute(
        select(
            Task.milestone_id,
            func.count(),
            func.count().filter(Task.status == TaskStatus.DONE),
        )
        .where(Task.milestone_id.in_(ids))
        .group_by(Task.milestone_id)
    )
    return {mid: (int(total), int(done)) for mid, total, done in rows.all() if mid is not None}


def roadmap_out(roadmap: Roadmap, stats: tuple[int, int]) -> RoadmapOut:
    total, done = stats
    return RoadmapOut.model_validate(
        {
            **{k: getattr(roadmap, k) for k in ("id", "title", "goal", "status", "target_date")},
            "created_at": roadmap.created_at,
            "updated_at": roadmap.updated_at,
            "progress": progress_of(total, done),
            "milestone_count": total,
            "done_count": done,
        }
    )


async def list_milestones(db: AsyncSession, roadmap_id: uuid.UUID) -> list[Milestone]:
    rows = await db.scalars(
        select(Milestone)
        .where(Milestone.roadmap_id == roadmap_id)
        .order_by(Milestone.position, Milestone.created_at)
    )
    return list(rows)


async def milestones_out(db: AsyncSession, milestones: list[Milestone]) -> list[MilestoneOut]:
    stats = await task_stats(db, (m.id for m in milestones))
    out = []
    for m in milestones:
        total, done = stats.get(m.id, (0, 0))
        item = MilestoneOut.model_validate(m)
        item.task_count, item.done_task_count = total, done
        out.append(item)
    return out


async def detail(db: AsyncSession, roadmap: Roadmap) -> RoadmapDetail:
    milestones = await list_milestones(db, roadmap.id)
    total = len(milestones)
    done = sum(1 for m in milestones if m.status == MilestoneStatus.DONE)
    base = roadmap_out(roadmap, (total, done))
    return RoadmapDetail(**base.model_dump(), milestones=await milestones_out(db, milestones))


async def list_roadmaps(db: AsyncSession, user_id: uuid.UUID) -> list[RoadmapOut]:
    status_rank = case({"active": 0, "paused": 1, "completed": 2}, value=Roadmap.status)
    roadmaps = list(
        await db.scalars(
            select(Roadmap)
            .where(Roadmap.user_id == user_id)
            .order_by(status_rank, Roadmap.updated_at.desc())
        )
    )
    stats = await milestone_stats(db, (r.id for r in roadmaps))
    return [roadmap_out(r, stats.get(r.id, (0, 0))) for r in roadmaps]


async def get_detail(db: AsyncSession, roadmap_id: uuid.UUID, user_id: uuid.UUID) -> RoadmapDetail:
    return await detail(db, await get_roadmap(db, roadmap_id, user_id))


def _milestone_from(data: MilestoneCreate, roadmap_id: uuid.UUID, position: int) -> Milestone:
    values: dict[str, Any] = data.model_dump(exclude={"position"}, mode="json")
    values["target_date"] = data.target_date
    values["status"] = data.status
    return Milestone(roadmap_id=roadmap_id, position=position, **values)


async def create_roadmap(
    db: AsyncSession, user_id: uuid.UUID, data: RoadmapCreate
) -> RoadmapDetail:
    roadmap = Roadmap(
        user_id=user_id,
        title=data.title,
        goal=data.goal,
        status=data.status,
        target_date=data.target_date,
    )
    db.add(roadmap)
    await db.flush()
    for i, m in enumerate(data.milestones):
        db.add(_milestone_from(m, roadmap.id, i))
    await db.commit()
    await invalidate_dashboard(user_id)
    return await detail(db, roadmap)


async def update_roadmap(
    db: AsyncSession, roadmap_id: uuid.UUID, user_id: uuid.UUID, data: RoadmapUpdate
) -> RoadmapDetail:
    roadmap = await get_roadmap(db, roadmap_id, user_id)
    for key, value in data.model_dump(exclude_unset=True).items():
        if value is None and key in NON_NULLABLE:
            continue
        setattr(roadmap, key, value)
    await db.commit()
    await invalidate_dashboard(user_id)
    return await detail(db, roadmap)


async def delete_roadmap(db: AsyncSession, roadmap_id: uuid.UUID, user_id: uuid.UUID) -> None:
    roadmap = await get_roadmap(db, roadmap_id, user_id)
    await db.delete(roadmap)
    await db.commit()
    await invalidate_dashboard(user_id)


async def _touch(roadmap_id: uuid.UUID, db: AsyncSession) -> None:
    roadmap = await db.get(Roadmap, roadmap_id)
    if roadmap is not None:
        roadmap.updated_at = utcnow()


async def add_milestone(
    db: AsyncSession, roadmap_id: uuid.UUID, user_id: uuid.UUID, data: MilestoneCreate
) -> MilestoneOut:
    roadmap = await get_roadmap(db, roadmap_id, user_id)
    current_max = await db.scalar(
        select(func.max(Milestone.position)).where(Milestone.roadmap_id == roadmap.id)
    )
    next_pos = 0 if current_max is None else int(current_max) + 1
    milestones = await list_milestones(db, roadmap.id)
    if data.position is not None and data.position < len(milestones):
        for m in milestones[data.position :]:
            m.position += 1
        next_pos = data.position
    milestone = _milestone_from(data, roadmap.id, next_pos)
    db.add(milestone)
    roadmap.updated_at = utcnow()
    await db.commit()
    await invalidate_dashboard(user_id)
    return (await milestones_out(db, [milestone]))[0]


async def update_milestone(
    db: AsyncSession, milestone_id: uuid.UUID, user_id: uuid.UUID, data: MilestoneUpdate
) -> MilestoneOut:
    milestone = await get_milestone(db, milestone_id, user_id)
    for key, value in data.model_dump(exclude_unset=True, mode="json").items():
        if value is None and key in NON_NULLABLE:
            continue
        if key == "target_date":
            value = data.target_date
        setattr(milestone, key, value)
    await _touch(milestone.roadmap_id, db)
    await db.commit()
    await invalidate_dashboard(user_id)
    return (await milestones_out(db, [milestone]))[0]


async def _repack(db: AsyncSession, roadmap_id: uuid.UUID) -> None:
    for i, m in enumerate(await list_milestones(db, roadmap_id)):
        m.position = i


async def delete_milestone(db: AsyncSession, milestone_id: uuid.UUID, user_id: uuid.UUID) -> None:
    milestone = await get_milestone(db, milestone_id, user_id)
    roadmap_id = milestone.roadmap_id
    await db.delete(milestone)
    await db.flush()
    await _repack(db, roadmap_id)
    await _touch(roadmap_id, db)
    await db.commit()
    await invalidate_dashboard(user_id)


async def reorder(
    db: AsyncSession, roadmap_id: uuid.UUID, user_id: uuid.UUID, ids: list[uuid.UUID]
) -> RoadmapDetail:
    roadmap = await get_roadmap(db, roadmap_id, user_id)
    milestones = {m.id: m for m in await list_milestones(db, roadmap.id)}
    if len(ids) != len(set(ids)) or set(ids) != set(milestones):
        raise AppError(
            "ids must list every milestone of this roadmap exactly once",
            code="INVALID_ORDER",
            status_code=422,
            details=[{"field": "ids", "message": "must match the roadmap's milestones exactly"}],
        )
    for position, mid in enumerate(ids):
        milestones[mid].position = position
    roadmap.updated_at = utcnow()
    await db.commit()  # one transaction: all positions or none
    await invalidate_dashboard(user_id)
    return await detail(db, roadmap)
