import uuid

from fastapi import APIRouter, status

from app.core.exceptions import error_responses
from app.db.session import DbSession
from app.features.auth.deps import CurrentUser
from app.features.profile import service
from app.features.profile.models import Education, Experience, Skill
from app.features.profile.schemas import (
    EducationCreate,
    EducationOut,
    EducationUpdate,
    ExperienceCreate,
    ExperienceOut,
    ExperienceUpdate,
    ProfileOut,
    ProfileUpdate,
    SkillCreate,
    SkillOut,
    SkillUpdate,
)

router = APIRouter(prefix="/profile", tags=["profile"], responses=error_responses(401))


@router.get("", response_model=ProfileOut, summary="Profile with experience, education, skills")
async def get_profile(user: CurrentUser, db: DbSession) -> ProfileOut:
    return await service.get_profile(db, user)


@router.put(
    "",
    response_model=ProfileOut,
    summary="Update the profile (partial; full_name/email update the user)",
    responses=error_responses(409, 422),
)
async def update_profile(body: ProfileUpdate, user: CurrentUser, db: DbSession) -> ProfileOut:
    return await service.update_profile(db, user, body)


# ---- experience ------------------------------------------------------------------------


@router.get("/experience", response_model=list[ExperienceOut])
async def list_experience(user: CurrentUser, db: DbSession) -> list[ExperienceOut]:
    return [ExperienceOut.model_validate(e) for e in await service.list_experience(db, user.id)]


@router.post(
    "/experience",
    response_model=ExperienceOut,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(422),
)
async def create_experience(
    body: ExperienceCreate, user: CurrentUser, db: DbSession
) -> ExperienceOut:
    item = await service.create_item(db, Experience, user.id, body.model_dump())
    return ExperienceOut.model_validate(item)


@router.patch(
    "/experience/{item_id}", response_model=ExperienceOut, responses=error_responses(404, 422)
)
async def update_experience(
    item_id: uuid.UUID, body: ExperienceUpdate, user: CurrentUser, db: DbSession
) -> ExperienceOut:
    item = await service.update_item(
        db, Experience, item_id, user.id, body.model_dump(exclude_unset=True)
    )
    return ExperienceOut.model_validate(item)


@router.delete(
    "/experience/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=error_responses(404),
)
async def delete_experience(item_id: uuid.UUID, user: CurrentUser, db: DbSession) -> None:
    await service.delete_item(db, Experience, item_id, user.id)


# ---- education -------------------------------------------------------------------------


@router.get("/education", response_model=list[EducationOut])
async def list_education(user: CurrentUser, db: DbSession) -> list[EducationOut]:
    return [EducationOut.model_validate(e) for e in await service.list_education(db, user.id)]


@router.post(
    "/education",
    response_model=EducationOut,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(422),
)
async def create_education(body: EducationCreate, user: CurrentUser, db: DbSession) -> EducationOut:
    item = await service.create_item(db, Education, user.id, body.model_dump())
    return EducationOut.model_validate(item)


@router.patch(
    "/education/{item_id}", response_model=EducationOut, responses=error_responses(404, 422)
)
async def update_education(
    item_id: uuid.UUID, body: EducationUpdate, user: CurrentUser, db: DbSession
) -> EducationOut:
    item = await service.update_item(
        db, Education, item_id, user.id, body.model_dump(exclude_unset=True)
    )
    return EducationOut.model_validate(item)


@router.delete(
    "/education/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=error_responses(404),
)
async def delete_education(item_id: uuid.UUID, user: CurrentUser, db: DbSession) -> None:
    await service.delete_item(db, Education, item_id, user.id)


# ---- skills ----------------------------------------------------------------------------


@router.get("/skills", response_model=list[SkillOut])
async def list_skills(user: CurrentUser, db: DbSession) -> list[SkillOut]:
    return [SkillOut.model_validate(s) for s in await service.list_skills(db, user.id)]


@router.post(
    "/skills",
    response_model=SkillOut,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(422),
)
async def create_skill(body: SkillCreate, user: CurrentUser, db: DbSession) -> SkillOut:
    item = await service.create_item(db, Skill, user.id, body.model_dump())
    return SkillOut.model_validate(item)


@router.patch("/skills/{item_id}", response_model=SkillOut, responses=error_responses(404, 422))
async def update_skill(
    item_id: uuid.UUID, body: SkillUpdate, user: CurrentUser, db: DbSession
) -> SkillOut:
    item = await service.update_item(
        db, Skill, item_id, user.id, body.model_dump(exclude_unset=True)
    )
    return SkillOut.model_validate(item)


@router.delete(
    "/skills/{item_id}", status_code=status.HTTP_204_NO_CONTENT, responses=error_responses(404)
)
async def delete_skill(item_id: uuid.UUID, user: CurrentUser, db: DbSession) -> None:
    await service.delete_item(db, Skill, item_id, user.id)
