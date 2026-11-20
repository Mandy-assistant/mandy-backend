import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.core.exceptions import error_responses
from app.db.session import DbSession
from app.features.auth.deps import CurrentUser
from app.features.jobs import service
from app.features.jobs.models import JobStatus
from app.features.jobs.schemas import JobCreate, JobEventOut, JobOut, JobStatusUpdate, JobUpdate
from app.shared.pagination import Page, Pagination

router = APIRouter(prefix="/jobs", tags=["jobs"], responses=error_responses(401))

SORT_PATTERN = r"^-?(updated_at|company|role|status|applied_at)$"


@router.get("", response_model=Page[JobOut], responses=error_responses(422))
async def list_jobs(
    user: CurrentUser,
    db: DbSession,
    pagination: Pagination,
    status_: Annotated[JobStatus | None, Query(alias="status")] = None,
    q: Annotated[str | None, Query(max_length=100, description="Search company/role")] = None,
    sort: Annotated[
        str,
        Query(pattern=SORT_PATTERN, description="Field, optional `-` prefix for descending"),
    ] = "-updated_at",
) -> Page[JobOut]:
    items, total = await service.list_jobs(db, user.id, pagination, status=status_, q=q, sort=sort)
    return Page[JobOut].build([JobOut.model_validate(j) for j in items], total, pagination)


@router.post(
    "", response_model=JobOut, status_code=status.HTTP_201_CREATED, responses=error_responses(422)
)
async def create_job(body: JobCreate, user: CurrentUser, db: DbSession) -> JobOut:
    return JobOut.model_validate(await service.create_job(db, user.id, body))


@router.get("/{job_id}", response_model=JobOut, responses=error_responses(404))
async def get_job(job_id: uuid.UUID, user: CurrentUser, db: DbSession) -> JobOut:
    return JobOut.model_validate(await service.get_job(db, job_id, user.id))


@router.patch("/{job_id}", response_model=JobOut, responses=error_responses(404, 422))
async def update_job(
    job_id: uuid.UUID, body: JobUpdate, user: CurrentUser, db: DbSession
) -> JobOut:
    return JobOut.model_validate(await service.update_job(db, job_id, user.id, body))


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT, responses=error_responses(404))
async def delete_job(job_id: uuid.UUID, user: CurrentUser, db: DbSession) -> None:
    await service.delete_job(db, job_id, user.id)


@router.patch(
    "/{job_id}/status",
    response_model=JobOut,
    summary="Move a job to another status (records a history event)",
    responses=error_responses(404, 422),
)
async def change_status(
    job_id: uuid.UUID, body: JobStatusUpdate, user: CurrentUser, db: DbSession
) -> JobOut:
    job = await service.change_status(db, job_id, user.id, body.status, body.position)
    return JobOut.model_validate(job)


@router.get(
    "/{job_id}/timeline",
    response_model=list[JobEventOut],
    summary="Status history, oldest first (creation has from_status=null)",
    responses=error_responses(404),
)
async def timeline(job_id: uuid.UUID, user: CurrentUser, db: DbSession) -> list[JobEventOut]:
    return [JobEventOut.model_validate(e) for e in await service.timeline(db, job_id, user.id)]
