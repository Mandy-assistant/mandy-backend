"""Resumes and their version history."""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.features.auth.models import User
from app.features.profile import service as profile_service
from app.features.resumes.models import Resume, ResumeTemplate, ResumeVersion
from app.features.resumes.schemas import (
    ResumeContent,
    ResumeCreate,
    ResumeHeader,
    ResumeLink,
    ResumeUpdate,
    Section,
    SectionItem,
)
from app.shared.ownership import get_owned_or_404


async def get_resume(db: AsyncSession, resume_id: uuid.UUID, user_id: uuid.UUID) -> Resume:
    return await get_owned_or_404(
        db, Resume, resume_id, user_id, code="RESUME_NOT_FOUND", message="Resume not found"
    )


async def list_resumes(db: AsyncSession, user_id: uuid.UUID) -> list[Resume]:
    rows = await db.scalars(
        select(Resume).where(Resume.user_id == user_id).order_by(Resume.updated_at.desc())
    )
    return list(rows)


def _dump(content: ResumeContent) -> dict[str, Any]:
    return content.model_dump(mode="json")


async def _create(
    db: AsyncSession,
    user_id: uuid.UUID,
    title: str,
    template: ResumeTemplate,
    content: ResumeContent,
) -> Resume:
    resume = Resume(
        user_id=user_id, title=title, template=template, content=_dump(content), current_version=1
    )
    db.add(resume)
    await db.flush()
    db.add(ResumeVersion(resume_id=resume.id, version=1, content=resume.content))
    await db.commit()
    return resume


async def create_resume(db: AsyncSession, user_id: uuid.UUID, data: ResumeCreate) -> Resume:
    return await _create(db, user_id, data.title, data.template, data.content or ResumeContent())


async def update_resume(
    db: AsyncSession, resume_id: uuid.UUID, user_id: uuid.UUID, data: ResumeUpdate
) -> Resume:
    resume = await get_resume(db, resume_id, user_id)
    if data.title is not None:
        resume.title = data.title
    if data.template is not None:
        resume.template = data.template
    if data.content is not None:
        resume.content = _dump(data.content)
    await db.commit()
    return resume


async def delete_resume(db: AsyncSession, resume_id: uuid.UUID, user_id: uuid.UUID) -> None:
    resume = await get_resume(db, resume_id, user_id)
    await db.delete(resume)
    await db.commit()


async def duplicate_resume(db: AsyncSession, resume_id: uuid.UUID, user_id: uuid.UUID) -> Resume:
    src = await get_resume(db, resume_id, user_id)
    content = ResumeContent.model_validate(src.content)
    return await _create(db, user_id, f"{src.title} (copy)"[:200], src.template, content)


async def _add_version(db: AsyncSession, resume: Resume) -> ResumeVersion:
    resume.current_version += 1
    version = ResumeVersion(
        resume_id=resume.id, version=resume.current_version, content=resume.content
    )
    db.add(version)
    await db.commit()
    return version


async def snapshot(db: AsyncSession, resume_id: uuid.UUID, user_id: uuid.UUID) -> ResumeVersion:
    return await _add_version(db, await get_resume(db, resume_id, user_id))


async def list_versions(
    db: AsyncSession, resume_id: uuid.UUID, user_id: uuid.UUID
) -> list[ResumeVersion]:
    await get_resume(db, resume_id, user_id)
    rows = await db.scalars(
        select(ResumeVersion)
        .where(ResumeVersion.resume_id == resume_id)
        .order_by(ResumeVersion.version.desc())
    )
    return list(rows)


async def restore_version(
    db: AsyncSession, resume_id: uuid.UUID, user_id: uuid.UUID, version: int
) -> Resume:
    resume = await get_resume(db, resume_id, user_id)
    old = await db.scalar(
        select(ResumeVersion).where(
            ResumeVersion.resume_id == resume_id, ResumeVersion.version == version
        )
    )
    if old is None:
        raise NotFoundError("Version not found", code="VERSION_NOT_FOUND")
    resume.content = dict(old.content)
    await _add_version(db, resume)
    return resume


# ---- from profile ----------------------------------------------------------------------


def _fmt_month(value: Any) -> str | None:
    return value.strftime("%b %Y") if value else None


async def build_content_from_profile(db: AsyncSession, user: User) -> ResumeContent:
    profile = await profile_service.get_or_create_profile(db, user.id)
    experience = await profile_service.list_experience(db, user.id)
    education = await profile_service.list_education(db, user.id)
    skills = await profile_service.list_skills(db, user.id)

    links = [
        ResumeLink(label=label.capitalize(), url=url)
        for label, url in (profile.links or {}).items()
        if url
    ]
    header = ResumeHeader(
        full_name=user.display_name,
        headline=profile.headline or "",
        email=user.email,
        phone=profile.phone or "",
        location=profile.location or "",
        links=links,
    )
    by_category: dict[str, list[str]] = {}
    for s in skills:
        by_category.setdefault(s.category.value, []).append(s.name)
    category_titles = {
        "language": "Languages",
        "framework": "Frameworks",
        "tool": "Tools",
        "ml": "Machine learning",
        "other": "Other",
    }
    sections = [
        Section(type="summary", title="Summary", text=profile.summary or ""),
        Section(
            type="experience",
            title="Experience",
            items=[
                SectionItem(
                    title=e.title,
                    subtitle=e.company,
                    location=e.location,
                    start_date=_fmt_month(e.start_date),
                    end_date="Present" if e.current else _fmt_month(e.end_date),
                    description=e.description,
                    bullets=list(e.highlights or []),
                )
                for e in experience
            ],
        ),
        Section(
            type="education",
            title="Education",
            items=[
                SectionItem(
                    title=" ".join(p for p in (e.degree, e.field) if p) or e.school,
                    subtitle=e.school,
                    start_date=_fmt_month(e.start_date),
                    end_date=_fmt_month(e.end_date),
                    description=e.description or (f"Grade: {e.grade}" if e.grade else None),
                )
                for e in education
            ],
        ),
        Section(
            type="skills",
            title="Skills",
            items=[
                SectionItem(title=category_titles.get(cat, cat.title()), tags=names)
                for cat, names in by_category.items()
            ],
        ),
        Section(type="projects", title="Projects", visible=False),
    ]
    return ResumeContent(header=header, sections=sections)


async def create_from_profile(
    db: AsyncSession, user: User, title: str, template: ResumeTemplate
) -> Resume:
    content = await build_content_from_profile(db, user)
    return await _create(db, user.id, title, template, content)
