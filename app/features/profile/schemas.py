import uuid
from datetime import date
from typing import Literal

from pydantic import BaseModel, EmailStr, Field

from app.features.profile.models import SkillCategory, SkillLevel
from app.shared.schemas import ORMModel

WorkMode = Literal["remote", "hybrid", "onsite"]


class Links(BaseModel):
    github: str | None = None
    linkedin: str | None = None
    portfolio: str | None = None
    website: str | None = None


class Preferences(BaseModel):
    locations: list[str] = []
    work_modes: list[WorkMode] = []
    salary_min: int | None = Field(default=None, ge=0)
    salary_max: int | None = Field(default=None, ge=0)
    currency: str = Field(default="INR", min_length=3, max_length=3)


# ---- experience ------------------------------------------------------------------------


class ExperienceCreate(BaseModel):
    company: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=200)
    location: str | None = Field(default=None, max_length=120)
    start_date: date
    end_date: date | None = None
    current: bool = False
    description: str | None = None
    highlights: list[str] = []


class ExperienceUpdate(BaseModel):
    company: str | None = Field(default=None, min_length=1, max_length=200)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    location: str | None = Field(default=None, max_length=120)
    start_date: date | None = None
    end_date: date | None = None
    current: bool | None = None
    description: str | None = None
    highlights: list[str] | None = None


class ExperienceOut(ORMModel):
    id: uuid.UUID
    company: str
    title: str
    location: str | None
    start_date: date
    end_date: date | None
    current: bool
    description: str | None
    highlights: list[str]


# ---- education -------------------------------------------------------------------------


class EducationCreate(BaseModel):
    school: str = Field(min_length=1, max_length=200)
    degree: str | None = Field(default=None, max_length=200)
    field: str | None = Field(default=None, max_length=200)
    start_date: date
    end_date: date | None = None
    grade: str | None = Field(default=None, max_length=50)
    description: str | None = None


class EducationUpdate(BaseModel):
    school: str | None = Field(default=None, min_length=1, max_length=200)
    degree: str | None = Field(default=None, max_length=200)
    field: str | None = Field(default=None, max_length=200)
    start_date: date | None = None
    end_date: date | None = None
    grade: str | None = Field(default=None, max_length=50)
    description: str | None = None


class EducationOut(ORMModel):
    id: uuid.UUID
    school: str
    degree: str | None
    field: str | None
    start_date: date
    end_date: date | None
    grade: str | None
    description: str | None


# ---- skills ----------------------------------------------------------------------------


class SkillCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    level: SkillLevel = SkillLevel.INTERMEDIATE
    category: SkillCategory = SkillCategory.OTHER


class SkillUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    level: SkillLevel | None = None
    category: SkillCategory | None = None


class SkillOut(ORMModel):
    id: uuid.UUID
    name: str
    level: SkillLevel
    category: SkillCategory


# ---- profile ---------------------------------------------------------------------------


class ProfileUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=100)
    email: EmailStr | None = None
    headline: str | None = Field(default=None, max_length=200)
    summary: str | None = None
    location: str | None = Field(default=None, max_length=120)
    phone: str | None = Field(default=None, max_length=40)
    links: Links | None = None
    target_roles: list[str] | None = None
    preferences: Preferences | None = None


class ProfileOut(BaseModel):
    full_name: str
    email: str
    headline: str | None
    summary: str | None
    location: str | None
    phone: str | None
    links: Links
    target_roles: list[str]
    preferences: Preferences
    completeness: int = Field(ge=0, le=100)
    experience: list[ExperienceOut]
    education: list[EducationOut]
    skills: list[SkillOut]
