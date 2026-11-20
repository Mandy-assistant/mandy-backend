import enum
import uuid
from typing import Any

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPrimaryKey, str_enum


class ResumeTemplate(enum.StrEnum):
    MODERN = "modern"
    CLASSIC = "classic"


class Resume(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "resumes"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    template: Mapped[ResumeTemplate] = mapped_column(
        str_enum(ResumeTemplate, "resume_template"), default=ResumeTemplate.MODERN
    )
    content: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    current_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")


class ResumeVersion(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "resume_versions"
    __table_args__ = (UniqueConstraint("resume_id", "version"),)

    resume_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("resumes.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    content: Mapped[dict[str, Any]] = mapped_column(JSONB)
