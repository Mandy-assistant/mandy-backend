import enum
import uuid
from datetime import date
from typing import Any

from sqlalchemy import ARRAY, Boolean, Date, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPrimaryKey, str_enum


class SkillLevel(enum.StrEnum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


class SkillCategory(enum.StrEnum):
    LANGUAGE = "language"
    FRAMEWORK = "framework"
    TOOL = "tool"
    ML = "ml"
    OTHER = "other"


def _user_fk(unique: bool = False) -> Mapped[uuid.UUID]:
    return mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=not unique, unique=unique
    )


class Profile(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "profiles"

    user_id: Mapped[uuid.UUID] = _user_fk(unique=True)
    headline: Mapped[str | None] = mapped_column(String(200))
    summary: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(String(120))
    phone: Mapped[str | None] = mapped_column(String(40))
    links: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    target_roles: Mapped[list[str]] = mapped_column(
        ARRAY(String(100)), default=list, server_default="{}"
    )
    preferences: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")


class Experience(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "experiences"

    user_id: Mapped[uuid.UUID] = _user_fk()
    company: Mapped[str] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(String(200))
    location: Mapped[str | None] = mapped_column(String(120))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    current: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    description: Mapped[str | None] = mapped_column(Text)
    highlights: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default="{}")


class Education(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "educations"

    user_id: Mapped[uuid.UUID] = _user_fk()
    school: Mapped[str] = mapped_column(String(200))
    degree: Mapped[str | None] = mapped_column(String(200))
    field: Mapped[str | None] = mapped_column(String(200))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    grade: Mapped[str | None] = mapped_column(String(50))
    description: Mapped[str | None] = mapped_column(Text)


class Skill(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "skills"

    user_id: Mapped[uuid.UUID] = _user_fk()
    name: Mapped[str] = mapped_column(String(100))
    level: Mapped[SkillLevel] = mapped_column(
        str_enum(SkillLevel, "skill_level"), default=SkillLevel.INTERMEDIATE
    )
    category: Mapped[SkillCategory] = mapped_column(
        str_enum(SkillCategory, "skill_category"), default=SkillCategory.OTHER
    )
