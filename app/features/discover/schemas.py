import uuid
from typing import Literal

from pydantic import BaseModel

from app.features.discover.models import MatchStatus
from app.shared.pagination import Page
from app.shared.schemas import ORMModel, UTCDateTime

Region = Literal["remote", "india", "anywhere"]


class JobFit(BaseModel):
    fit: int
    reason: str
    gaps: str


class PostingOut(ORMModel):
    id: uuid.UUID
    source: str
    url: str
    company: str
    role: str
    location: str
    remote: bool
    regions: list[str]
    tags: list[str]
    salary: str | None
    employment_type: str | None
    summary: str
    logo_url: str | None
    posted_at: UTCDateTime
    match_score: int = 0
    """0-100 from your interests and skills (before the AI looks at it)."""
    fit: JobFit | None = None
    status: MatchStatus = MatchStatus.NEW
    job_id: uuid.UUID | None = None


class DiscoverPage(Page[PostingOut]):
    personalizing: bool = False


class DiscoverRefreshResult(BaseModel):
    added: int
