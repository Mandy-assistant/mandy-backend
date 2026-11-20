import enum
import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, Timestamps, UUIDPrimaryKey, str_enum
from app.features.roadmaps.models import Milestone, Roadmap


class TaskPriority(enum.StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TaskStatus(enum.StrEnum):
    TODO = "todo"
    DONE = "done"


class Task(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "tasks"
    __table_args__ = (
        Index("ix_tasks_user_id_status_due_date", "user_id", "status", "due_date"),
        Index("ix_tasks_user_id_completed_at", "user_id", "completed_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(Text)
    due_date: Mapped[date | None] = mapped_column(Date)
    priority: Mapped[TaskPriority] = mapped_column(
        str_enum(TaskPriority, "task_priority"), default=TaskPriority.MEDIUM
    )
    status: Mapped[TaskStatus] = mapped_column(
        str_enum(TaskStatus, "task_status"), default=TaskStatus.TODO
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    roadmap_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("roadmaps.id", ondelete="SET NULL"), index=True
    )
    milestone_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("milestones.id", ondelete="SET NULL"), index=True
    )

    roadmap: Mapped[Roadmap | None] = relationship(lazy="joined", viewonly=True)
    milestone: Mapped[Milestone | None] = relationship(lazy="joined", viewonly=True)

    @property
    def roadmap_title(self) -> str | None:
        return self.roadmap.title if self.roadmap else None

    @property
    def milestone_title(self) -> str | None:
        return self.milestone.title if self.milestone else None
