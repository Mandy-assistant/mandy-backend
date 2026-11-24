from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.shared.text import normalise_tag

JobRegion = Literal["remote", "india", "anywhere"]


def _clean(topics: list[str]) -> list[str]:
    return list(dict.fromkeys(t for t in (normalise_tag(x) for x in topics) if t))


class LearnedTerm(BaseModel):
    term: str
    weight: float


class InterestsOut(BaseModel):
    followed: list[str]
    muted: list[str]
    job_regions: list[JobRegion]
    learned: list[LearnedTerm] = Field(description="Strongest learned interests, highest first")
    context: str = Field(description="What the AI is told about you")


class InterestsUpdate(BaseModel):
    followed: list[str] | None = Field(default=None, max_length=50)
    muted: list[str] | None = Field(default=None, max_length=50)
    job_regions: list[JobRegion] | None = Field(default=None, max_length=3)

    @field_validator("followed", "muted")
    @classmethod
    def _topics(cls, value: list[str] | None) -> list[str] | None:
        return _clean(value) if value is not None else None
