"""Job applications with a status history."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationFailed
from app.features.dashboard.cache import invalidate_dashboard
from app.features.jobs.models import Job, JobStatus, JobStatusEvent
from app.features.jobs.schemas import JobCreate, JobUpdate
from app.shared.ownership import get_owned_or_404
from app.shared.pagination import PageParams, paginate

SORT_COLUMNS = {
    "updated_at": Job.updated_at,
    "company": Job.company,
    "role": Job.role,
    "status": Job.status,
    "applied_at": Job.applied_at,
}
NON_NULLABLE = {"company", "role", "currency", "status", "tags", "position"}


def escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def get_job(db: AsyncSession, job_id: uuid.UUID, user_id: uuid.UUID) -> Job:
    return await get_owned_or_404(
        db, Job, job_id, user_id, code="JOB_NOT_FOUND", message="Job not found"
    )


async def list_jobs(
    db: AsyncSession,
    user_id: uuid.UUID,
    params: PageParams,
    *,
    status: JobStatus | None = None,
    q: str | None = None,
    sort: str = "-updated_at",
) -> tuple[list[Job], int]:
    stmt = select(Job).where(Job.user_id == user_id)
    if status is not None:
        stmt = stmt.where(Job.status == status)
    if q and q.strip():
        pattern = f"%{escape_like(q.strip())}%"
        stmt = stmt.where(
            or_(Job.company.ilike(pattern, escape="\\"), Job.role.ilike(pattern, escape="\\"))
        )
    column = SORT_COLUMNS[sort.lstrip("-")]
    order = column.desc().nulls_last() if sort.startswith("-") else column.asc().nulls_last()
    stmt = stmt.order_by(order, Job.id)
    return await paginate(db, stmt, params)


def _check_salary(job: Job) -> None:
    if (
        job.salary_min is not None
        and job.salary_max is not None
        and job.salary_max < job.salary_min
    ):
        raise ValidationFailed(
            "salary_max", "salary_max must be greater than or equal to salary_min"
        )


async def _next_position(db: AsyncSession, user_id: uuid.UUID, status: JobStatus) -> int:
    current = await db.scalar(
        select(func.max(Job.position)).where(Job.user_id == user_id, Job.status == status)
    )
    return 0 if current is None else int(current) + 1


def _today() -> Any:
    return datetime.now(UTC).date()


async def create_job(db: AsyncSession, user_id: uuid.UUID, data: JobCreate) -> Job:
    values = data.model_dump()
    position = values.pop("position")
    job = Job(user_id=user_id, **values)
    _check_salary(job)
    job.position = (
        position if position is not None else await _next_position(db, user_id, job.status)
    )
    if job.status == JobStatus.APPLIED and job.applied_at is None:
        job.applied_at = _today()
    db.add(job)
    await db.flush()
    db.add(JobStatusEvent(job_id=job.id, from_status=None, to_status=job.status))
    await db.commit()
    await invalidate_dashboard(user_id)
    return job


async def _apply_status(
    db: AsyncSession, job: Job, status: JobStatus, position: int | None
) -> None:
    if status != job.status:
        db.add(JobStatusEvent(job_id=job.id, from_status=job.status, to_status=status))
        if position is None:
            position = await _next_position(db, job.user_id, status)
        job.status = status
        if status == JobStatus.APPLIED and job.applied_at is None:
            job.applied_at = _today()
    if position is not None:
        job.position = position


async def update_job(
    db: AsyncSession, job_id: uuid.UUID, user_id: uuid.UUID, data: JobUpdate
) -> Job:
    job = await get_job(db, job_id, user_id)
    changes = data.model_dump(exclude_unset=True)
    status = changes.pop("status", None)
    position = changes.pop("position", None)
    for key, value in changes.items():
        if value is None and key in NON_NULLABLE:
            continue
        setattr(job, key, value)
    _check_salary(job)
    if status is not None or position is not None:
        await _apply_status(db, job, status or job.status, position)
    await db.commit()
    await invalidate_dashboard(user_id)
    return job


async def change_status(
    db: AsyncSession, job_id: uuid.UUID, user_id: uuid.UUID, status: JobStatus, position: int | None
) -> Job:
    job = await get_job(db, job_id, user_id)
    await _apply_status(db, job, status, position)
    await db.commit()
    await invalidate_dashboard(user_id)
    return job


async def delete_job(db: AsyncSession, job_id: uuid.UUID, user_id: uuid.UUID) -> None:
    job = await get_job(db, job_id, user_id)
    await db.delete(job)
    await db.commit()
    await invalidate_dashboard(user_id)


async def timeline(db: AsyncSession, job_id: uuid.UUID, user_id: uuid.UUID) -> list[JobStatusEvent]:
    await get_job(db, job_id, user_id)
    rows = await db.scalars(
        select(JobStatusEvent)
        .where(JobStatusEvent.job_id == job_id)
        .order_by(JobStatusEvent.changed_at, JobStatusEvent.created_at)
    )
    return list(rows)
