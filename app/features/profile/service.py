"""Profile, experience, education and skills — always scoped to the current user."""

import uuid
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, ValidationFailed
from app.features.auth.models import User
from app.features.dashboard.cache import invalidate_dashboard
from app.features.profile.models import Education, Experience, Profile, Skill
from app.features.profile.schemas import (
    EducationOut,
    ExperienceOut,
    Links,
    Preferences,
    ProfileOut,
    ProfileUpdate,
    SkillOut,
)
from app.shared.ownership import get_owned_or_404

SubModel = type[Experience] | type[Education] | type[Skill]

NOT_FOUND = {
    Experience: ("EXPERIENCE_NOT_FOUND", "Experience not found"),
    Education: ("EDUCATION_NOT_FOUND", "Education not found"),
    Skill: ("SKILL_NOT_FOUND", "Skill not found"),
}


NON_NULLABLE = {
    "company",
    "title",
    "start_date",
    "current",
    "highlights",
    "school",
    "name",
    "level",
    "category",
}


def check_dates(start: date | None, end: date | None) -> None:
    if start and end and end < start:
        raise ValidationFailed("end_date", "end_date must be on or after start_date")


async def get_or_create_profile(db: AsyncSession, user_id: uuid.UUID) -> Profile:
    profile = await db.scalar(select(Profile).where(Profile.user_id == user_id))
    if profile is None:
        profile = Profile(user_id=user_id)
        db.add(profile)
        await db.flush()
    return profile


async def list_experience(db: AsyncSession, user_id: uuid.UUID) -> list[Experience]:
    rows = await db.scalars(
        select(Experience)
        .where(Experience.user_id == user_id)
        .order_by(Experience.current.desc(), Experience.start_date.desc())
    )
    return list(rows)


async def list_education(db: AsyncSession, user_id: uuid.UUID) -> list[Education]:
    rows = await db.scalars(
        select(Education).where(Education.user_id == user_id).order_by(Education.start_date.desc())
    )
    return list(rows)


async def list_skills(db: AsyncSession, user_id: uuid.UUID) -> list[Skill]:
    rows = await db.scalars(
        select(Skill).where(Skill.user_id == user_id).order_by(Skill.category, Skill.name)
    )
    return list(rows)


def compute_completeness(
    user: User, profile: Profile, n_experience: int, n_education: int, n_skills: int
) -> int:
    links = profile.links or {}
    checks = [
        bool(user.display_name),
        bool(user.email),
        bool(profile.headline),
        bool(profile.summary),
        bool(profile.location),
        bool(profile.phone),
        any(links.values()),
        bool(profile.target_roles),
        n_experience > 0,
        n_education > 0,
        n_skills >= 3,
    ]
    return round(100 * sum(checks) / len(checks))


async def get_profile(db: AsyncSession, user: User) -> ProfileOut:
    profile = await get_or_create_profile(db, user.id)
    await db.commit()
    experience = await list_experience(db, user.id)
    education = await list_education(db, user.id)
    skills = await list_skills(db, user.id)
    return ProfileOut(
        full_name=user.display_name,
        email=user.email,
        headline=profile.headline,
        summary=profile.summary,
        location=profile.location,
        phone=profile.phone,
        links=Links.model_validate(profile.links or {}),
        target_roles=list(profile.target_roles or []),
        preferences=Preferences.model_validate(profile.preferences or {}),
        completeness=compute_completeness(
            user, profile, len(experience), len(education), len(skills)
        ),
        experience=[ExperienceOut.model_validate(e) for e in experience],
        education=[EducationOut.model_validate(e) for e in education],
        skills=[SkillOut.model_validate(s) for s in skills],
    )


async def update_profile(db: AsyncSession, user: User, data: ProfileUpdate) -> ProfileOut:
    profile = await get_or_create_profile(db, user.id)
    changes = data.model_dump(exclude_unset=True)
    if "full_name" in changes and changes["full_name"] is not None:
        user.display_name = changes.pop("full_name")
    if "email" in changes and changes["email"] is not None:
        user.email = str(changes.pop("email"))
    changes.pop("full_name", None)
    changes.pop("email", None)
    if "links" in changes:
        changes["links"] = changes["links"] or {}
    if "preferences" in changes:
        prefs = changes["preferences"] or {}
        lo, hi = prefs.get("salary_min"), prefs.get("salary_max")
        if lo is not None and hi is not None and hi < lo:
            raise ValidationFailed("preferences.salary_max", "salary_max must be >= salary_min")
        changes["preferences"] = prefs
    if "target_roles" in changes:
        changes["target_roles"] = changes["target_roles"] or []
    for key, value in changes.items():
        setattr(profile, key, value)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError("That email is already in use", code="EMAIL_TAKEN") from exc
    await invalidate_dashboard(user.id)
    return await get_profile(db, user)


# ---- generic sub-resource CRUD ---------------------------------------------------------


async def create_item(
    db: AsyncSession, model: SubModel, user_id: uuid.UUID, data: dict[str, Any]
) -> Any:
    check_dates(data.get("start_date"), data.get("end_date"))
    item = model(user_id=user_id, **data)
    db.add(item)
    await db.commit()
    return item


async def update_item(
    db: AsyncSession, model: SubModel, item_id: uuid.UUID, user_id: uuid.UUID, data: dict[str, Any]
) -> Any:
    code, message = NOT_FOUND[model]
    item: Any = await get_owned_or_404(db, model, item_id, user_id, code=code, message=message)
    for key, value in data.items():
        if value is None and key in NON_NULLABLE:
            continue
        setattr(item, key, value)
    check_dates(getattr(item, "start_date", None), getattr(item, "end_date", None))
    await db.commit()
    return item


async def delete_item(
    db: AsyncSession, model: SubModel, item_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    code, message = NOT_FOUND[model]
    item = await get_owned_or_404(db, model, item_id, user_id, code=code, message=message)
    await db.delete(item)
    await db.commit()
