"""Build or revise a resume from a plain-language prompt.

The prompt decides the template, the look (accent colour, font, density) and the content: what
to lead with, what to cut, which job to tailor to. The facts come only from the user's profile
(or the resume being revised) and from details the user wrote in the prompt itself.
"""

import json
import uuid
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ai import AIClient
from app.features.auth.models import User
from app.features.personalize import service as interests
from app.features.resumes import service
from app.features.resumes.models import Resume, ResumeTemplate
from app.features.resumes.schemas import (
    ResumeContent,
    ResumeGenerate,
    ResumeHeader,
    ResumeRevise,
    ResumeStyle,
    Section,
    SectionItem,
    SectionType,
)

# ---- what the model fills in (no ids or defaults: Gemini's schema support is strict) --------


class PlanItem(BaseModel):
    title: str | None
    subtitle: str | None
    location: str | None
    start_date: str | None
    end_date: str | None
    description: str | None
    bullets: list[str]
    tags: list[str]
    url: str | None


class PlanSection(BaseModel):
    type: SectionType
    title: str
    text: str | None = Field(description="Only for the summary section")
    items: list[PlanItem]


class PlanStyle(BaseModel):
    accent: str = Field(description="Hex colour like #1f3a8a")
    font: Literal["sans", "serif", "mono"]
    density: Literal["compact", "comfortable"]


class ResumePlan(BaseModel):
    title: str = Field(description="Short name for this resume, e.g. 'Backend - Stripe'")
    template: Literal["modern", "classic"]
    style: PlanStyle
    headline: str
    sections: list[PlanSection]
    notes: str = Field(description="1-3 sentences: what you did and anything you could not do")


SYSTEM = """You are an expert resume writer and designer. Produce a complete resume as JSON.

LOOK: pick `template` ("modern": clean sans with an accent sidebar feel; "classic": traditional,
centred serif headings) and `style` (accent hex colour, font, density) from what the user asks.
If they don't say, choose a professional default (modern, sans, comfortable, a calm accent).
"One page" or "concise" means density "compact" and fewer bullets.

CONTENT: use ONLY facts from the PROFILE / CURRENT RESUME and from details the user writes in
their request. Never invent employers, job titles, dates, degrees, schools, numbers, metrics or
links. You may reword, reorder, merge, shorten, drop items and choose which sections to include
(section types: summary, experience, education, skills, projects). Strong bullets start with an
action verb and show impact; quantify only with numbers that are given. When a job description
is given, tailor the summary, the order and the wording to it, and surface matching skills.
Skills: group into items whose `title` is the group name and `tags` the skills.
Dates stay as given (e.g. "Jan 2023", "Present").
If the user asks for something the facts can't support, leave it out and say so in `notes`."""


def _to_content(plan: ResumePlan, header: ResumeHeader) -> ResumeContent:
    sections = [
        Section(
            type=s.type,
            title=s.title[:100] or s.type.title(),
            text=s.text if s.type == "summary" else None,
            items=[
                SectionItem(
                    title=i.title,
                    subtitle=i.subtitle,
                    location=i.location,
                    start_date=i.start_date,
                    end_date=i.end_date,
                    description=i.description,
                    bullets=[b for b in i.bullets if b.strip()][:30],
                    tags=[t for t in i.tags if t.strip()][:50],
                    url=i.url if i.url and i.url.startswith(("http://", "https://")) else None,
                )
                for i in s.items[:50]
            ],
        )
        for s in plan.sections[:20]
    ]
    try:
        style = ResumeStyle(
            accent=plan.style.accent, font=plan.style.font, density=plan.style.density
        )
    except ValueError:
        style = ResumeStyle(font=plan.style.font, density=plan.style.density)
    header = header.model_copy(update={"headline": plan.headline.strip()[:200] or header.headline})
    return ResumeContent(header=header, sections=sections, style=style)


def _facts(content: ResumeContent) -> str:
    """The resume as compact JSON without ids, for the prompt."""
    data = content.model_dump(mode="json", exclude={"style": True})
    for section in data["sections"]:
        section.pop("id", None)
        for item in section["items"]:
            item.pop("id", None)
    return json.dumps(data, ensure_ascii=False)


def _request(prompt: str, job_description: str | None) -> str:
    out = f"USER REQUEST:\n{prompt.strip()}"
    if job_description and job_description.strip():
        out += f"\n\nJOB DESCRIPTION TO TAILOR TO:\n{job_description.strip()}"
    return out


async def generate(
    db: AsyncSession, user: User, ai: AIClient, data: ResumeGenerate
) -> tuple[Resume, str]:
    profile = await service.build_content_from_profile(db, user)
    ctx = await interests.context(db, user)
    plan = await ai.generate_structured(
        system=SYSTEM,
        prompt=(
            f"{_request(data.prompt, data.job_description)}\n\n"
            f"ABOUT THE USER:\n{ctx}\n\nPROFILE:\n{_facts(profile)}"
        ),
        schema=ResumePlan,
    )
    content = _to_content(plan, profile.header)
    title = (data.title or plan.title or "AI resume").strip()[:200]
    resume = await service.create_resume_raw(
        db, user.id, title, ResumeTemplate(plan.template), content
    )
    return resume, plan.notes.strip()


async def revise(
    db: AsyncSession, user: User, ai: AIClient, resume_id: uuid.UUID, data: ResumeRevise
) -> tuple[Resume, str]:
    resume = await service.get_resume(db, resume_id, user.id)
    current = ResumeContent.model_validate(resume.content)
    style = current.style or ResumeStyle()
    plan = await ai.generate_structured(
        system=SYSTEM,
        prompt=(
            f"{_request(data.prompt, data.job_description)}\n\n"
            f"CURRENT LOOK: template {resume.template.value}, accent {style.accent}, "
            f"font {style.font}, density {style.density} (keep it unless asked to change)\n\n"
            f"CURRENT RESUME:\n{_facts(current)}"
        ),
        schema=ResumePlan,
    )
    content = _to_content(plan, current.header)
    resume.template = ResumeTemplate(plan.template)
    resume.content = content.model_dump(mode="json")
    await service.add_version(db, resume)  # one undo step per AI revision
    return resume, plan.notes.strip()
