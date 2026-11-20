import uuid
from datetime import date

from pydantic import BaseModel, Field

from app.features.jobs.models import JobStatus
from app.shared.schemas import ORMModel, UTCDateTime, UTCInput


class JobBase(BaseModel):
    location: str | None = Field(default=None, max_length=120)
    url: str | None = Field(default=None, max_length=1000)
    salary_min: int | None = Field(default=None, ge=0)
    salary_max: int | None = Field(default=None, ge=0)
    applied_at: date | None = None
    interview_at: UTCInput | None = None
    notes: str | None = Field(default=None, max_length=10_000)
    contact: str | None = Field(default=None, max_length=200)


class JobCreate(JobBase):
    company: str = Field(min_length=1, max_length=200, examples=["Vercel"])
    role: str = Field(min_length=1, max_length=200, examples=["Frontend Engineer"])
    currency: str = Field(default="INR", min_length=3, max_length=3)
    status: JobStatus = JobStatus.SAVED
    tags: list[str] = Field(default=[], max_length=20)
    position: int | None = Field(default=None, ge=0)


class JobUpdate(JobBase):
    company: str | None = Field(default=None, min_length=1, max_length=200)
    role: str | None = Field(default=None, min_length=1, max_length=200)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    status: JobStatus | None = None
    tags: list[str] | None = Field(default=None, max_length=20)
    position: int | None = Field(default=None, ge=0)


class JobStatusUpdate(BaseModel):
    status: JobStatus
    position: int | None = Field(
        default=None,
        ge=0,
        description="0-based index within the target status column after the move "
        "(default: top). Both columns are renumbered to 0..n-1.",
    )


class JobOut(ORMModel):
    id: uuid.UUID
    company: str
    role: str
    location: str | None
    url: str | None
    salary_min: int | None
    salary_max: int | None
    currency: str
    status: JobStatus
    applied_at: date | None
    interview_at: UTCDateTime | None
    notes: str | None
    contact: str | None
    tags: list[str]
    position: int
    created_at: UTCDateTime
    updated_at: UTCDateTime


class JobEventOut(ORMModel):
    id: uuid.UUID
    from_status: JobStatus | None
    to_status: JobStatus
    changed_at: UTCDateTime
