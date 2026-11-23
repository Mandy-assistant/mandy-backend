import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    ARRAY,
    Boolean,
    DateTime,
    ForeignKey,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPrimaryKey, str_enum


class JobPosting(UUIDPrimaryKey, Timestamps, Base):
    """An opening pulled from a public job board. Shared across users."""

    __tablename__ = "job_postings"

    source: Mapped[str] = mapped_column(String(50), index=True)
    url: Mapped[str] = mapped_column(String(1000), unique=True)
    company: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(300))
    location: Mapped[str] = mapped_column(String(200), default="", server_default="")
    remote: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # Where an Indian resident can take it: "remote" (worldwide/APAC remote), "india" (in India)
    regions: Mapped[list[str]] = mapped_column(ARRAY(String(20)), default=list, server_default="{}")
    tags: Mapped[list[str]] = mapped_column(ARRAY(String(50)), default=list, server_default="{}")
    salary: Mapped[str | None] = mapped_column(String(120))
    employment_type: Mapped[str | None] = mapped_column(String(60))
    summary: Mapped[str] = mapped_column(Text, default="", server_default="")
    logo_url: Mapped[str | None] = mapped_column(String(1000))
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class MatchStatus(enum.StrEnum):
    NEW = "new"
    HIDDEN = "hidden"
    TRACKED = "tracked"


class JobMatch(UUIDPrimaryKey, Timestamps, Base):
    """Per-user state for a posting: the AI's fit assessment and whether it was hidden/tracked."""

    __tablename__ = "job_matches"
    __table_args__ = (UniqueConstraint("user_id", "posting_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    posting_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("job_postings.id", ondelete="CASCADE"), index=True
    )
    fit: Mapped[int | None] = mapped_column(SmallInteger)
    reason: Mapped[str] = mapped_column(String(400), default="", server_default="")
    gaps: Mapped[str] = mapped_column(String(400), default="", server_default="")
    status: Mapped[MatchStatus] = mapped_column(
        str_enum(MatchStatus, "match_status"), default=MatchStatus.NEW, server_default="new"
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
