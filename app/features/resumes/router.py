import uuid

from fastapi import APIRouter, status

from app.core.exceptions import error_responses
from app.db.session import DbSession
from app.features.auth.deps import CurrentUser
from app.features.resumes import service
from app.features.resumes.schemas import (
    ResumeCreate,
    ResumeFromProfile,
    ResumeOut,
    ResumeUpdate,
    ResumeVersionOut,
)

router = APIRouter(prefix="/resumes", tags=["resumes"], responses=error_responses(401))


@router.get("", response_model=list[ResumeOut])
async def list_resumes(user: CurrentUser, db: DbSession) -> list[ResumeOut]:
    return [ResumeOut.model_validate(r) for r in await service.list_resumes(db, user.id)]


@router.post(
    "",
    response_model=ResumeOut,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(422),
)
async def create_resume(body: ResumeCreate, user: CurrentUser, db: DbSession) -> ResumeOut:
    return ResumeOut.model_validate(await service.create_resume(db, user.id, body))


@router.post(
    "/from-profile",
    response_model=ResumeOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a resume pre-filled from the profile",
    responses=error_responses(422),
)
async def create_from_profile(
    body: ResumeFromProfile, user: CurrentUser, db: DbSession
) -> ResumeOut:
    resume = await service.create_from_profile(db, user, body.title, body.template)
    return ResumeOut.model_validate(resume)


@router.get("/{resume_id}", response_model=ResumeOut, responses=error_responses(404))
async def get_resume(resume_id: uuid.UUID, user: CurrentUser, db: DbSession) -> ResumeOut:
    return ResumeOut.model_validate(await service.get_resume(db, resume_id, user.id))


@router.patch("/{resume_id}", response_model=ResumeOut, responses=error_responses(404, 422))
async def update_resume(
    resume_id: uuid.UUID, body: ResumeUpdate, user: CurrentUser, db: DbSession
) -> ResumeOut:
    return ResumeOut.model_validate(await service.update_resume(db, resume_id, user.id, body))


@router.delete(
    "/{resume_id}", status_code=status.HTTP_204_NO_CONTENT, responses=error_responses(404)
)
async def delete_resume(resume_id: uuid.UUID, user: CurrentUser, db: DbSession) -> None:
    await service.delete_resume(db, resume_id, user.id)


@router.post(
    "/{resume_id}/duplicate",
    response_model=ResumeOut,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(404),
)
async def duplicate_resume(resume_id: uuid.UUID, user: CurrentUser, db: DbSession) -> ResumeOut:
    return ResumeOut.model_validate(await service.duplicate_resume(db, resume_id, user.id))


@router.post(
    "/{resume_id}/versions",
    response_model=ResumeVersionOut,
    status_code=status.HTTP_201_CREATED,
    summary="Snapshot the current content as a new version",
    responses=error_responses(404),
)
async def create_version(
    resume_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> ResumeVersionOut:
    return ResumeVersionOut.model_validate(await service.snapshot(db, resume_id, user.id))


@router.get(
    "/{resume_id}/versions",
    response_model=list[ResumeVersionOut],
    summary="Versions, newest first",
    responses=error_responses(404),
)
async def list_versions(
    resume_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> list[ResumeVersionOut]:
    versions = await service.list_versions(db, resume_id, user.id)
    return [ResumeVersionOut.model_validate(v) for v in versions]


@router.post(
    "/{resume_id}/versions/{version}/restore",
    response_model=ResumeOut,
    summary="Restore a version (creates a new version)",
    responses=error_responses(404),
)
async def restore_version(
    resume_id: uuid.UUID, version: int, user: CurrentUser, db: DbSession
) -> ResumeOut:
    resume = await service.restore_version(db, resume_id, user.id, version)
    return ResumeOut.model_validate(resume)
