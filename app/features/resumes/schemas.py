import uuid
from typing import Literal

from pydantic import BaseModel, Field

from app.features.resumes.models import ResumeTemplate
from app.shared.schemas import ORMModel, UTCDateTime

SectionType = Literal["summary", "experience", "education", "skills", "projects"]


def _short_id() -> str:
    return uuid.uuid4().hex[:12]


class ResumeLink(BaseModel):
    label: str = Field(max_length=50)
    url: str = Field(max_length=500)


class ResumeHeader(BaseModel):
    full_name: str = ""
    headline: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    links: list[ResumeLink] = Field(default=[], max_length=10)


class SectionItem(BaseModel):
    id: str = Field(default_factory=_short_id, max_length=64)
    title: str | None = None
    subtitle: str | None = None
    location: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    description: str | None = None
    bullets: list[str] = Field(default=[], max_length=30)
    tags: list[str] = Field(default=[], max_length=50)
    url: str | None = None


class Section(BaseModel):
    id: str = Field(default_factory=_short_id, max_length=64)
    type: SectionType
    title: str = Field(max_length=100)
    visible: bool = True
    text: str | None = None
    items: list[SectionItem] = Field(default=[], max_length=50)


class ResumeStyle(BaseModel):
    """Look of the rendered resume (set by hand or by the AI from a prompt)."""

    accent: str = Field(default="#7c5cff", pattern=r"^#[0-9a-fA-F]{6}$")
    font: Literal["sans", "serif", "mono"] = "sans"
    density: Literal["compact", "comfortable"] = "comfortable"


class ResumeContent(BaseModel):
    header: ResumeHeader = ResumeHeader()
    sections: list[Section] = Field(default=[], max_length=20)
    style: ResumeStyle | None = None


class ResumeCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    template: ResumeTemplate = ResumeTemplate.MODERN
    content: ResumeContent | None = None


class ResumeUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    template: ResumeTemplate | None = None
    content: ResumeContent | None = None


class ResumeFromProfile(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    template: ResumeTemplate = ResumeTemplate.MODERN


class ResumeOut(ORMModel):
    id: uuid.UUID
    title: str
    template: ResumeTemplate
    content: ResumeContent
    current_version: int
    created_at: UTCDateTime
    updated_at: UTCDateTime


class ResumeVersionOut(ORMModel):
    id: uuid.UUID
    version: int
    content: ResumeContent
    created_at: UTCDateTime


class ResumeGenerate(BaseModel):
    prompt: str = Field(
        min_length=3,
        max_length=4000,
        description="Describe the template, look and content you want",
        examples=["One page, classic serif, navy accent. Lead with my Python and ML work."],
    )
    job_description: str | None = Field(
        default=None, max_length=12000, description="Paste a job post to tailor the resume to it"
    )
    title: str | None = Field(default=None, max_length=200)


class ResumeRevise(BaseModel):
    prompt: str = Field(
        min_length=3,
        max_length=4000,
        examples=["Make it fit one page and emphasise backend work"],
    )
    job_description: str | None = Field(default=None, max_length=12000)


class ResumeAIResult(BaseModel):
    resume: ResumeOut
    notes: str = Field(description="What the AI did and anything it could not do")
