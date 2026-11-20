import enum
import uuid
from datetime import date, datetime

from sqlalchemy import ARRAY, Date, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPrimaryKey, str_enum, utcnow


class JobStatus(enum.StrEnum):
    SAVED = "saved"
    APPLIED = "applied"
    INTERVIEW = "interview"
    OFFER = "offer"
    REJECTED = "rejected"


class Job(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_user_id_status", "user_id", "status"),
        Index("ix_jobs_user_id_updated_at", "user_id", "updated_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    company: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(200))
    location: Mapped[str | None] = mapped_column(String(120))
    url: Mapped[str | None] = mapped_column(String(1000))
    salary_min: Mapped[int | None] = mapped_column(Integer)
    salary_max: Mapped[int | None] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="INR", server_default="INR")
    status: Mapped[JobStatus] = mapped_column(
        str_enum(JobStatus, "job_status"), default=JobStatus.SAVED
    )
    applied_at: Mapped[date | None] = mapped_column(Date)
    interview_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)
    contact: Mapped[str | None] = mapped_column(String(200))
    tags: Mapped[list[str]] = mapped_column(ARRAY(String(50)), default=list, server_default="{}")
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class JobStatusEvent(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "job_status_events"

    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    from_status: Mapped[JobStatus | None] = mapped_column(str_enum(JobStatus, "from_status"))
    to_status: Mapped[JobStatus] = mapped_column(str_enum(JobStatus, "to_status"))
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
