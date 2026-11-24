import enum
import uuid
from datetime import date
from typing import Any

from sqlalchemy import Date, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPrimaryKey, str_enum


class RoadmapStatus(enum.StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"


class MilestoneStatus(enum.StrEnum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    DONE = "done"


class Roadmap(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "roadmaps"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    goal: Mapped[str | None] = mapped_column(Text)
    status: Mapped[RoadmapStatus] = mapped_column(
        str_enum(RoadmapStatus, "roadmap_status"), default=RoadmapStatus.ACTIVE
    )
    target_date: Mapped[date | None] = mapped_column(Date)


class Milestone(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "milestones"
    __table_args__ = (Index("ix_milestones_roadmap_id_position", "roadmap_id", "position"),)

    roadmap_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("roadmaps.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    resources: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default="[]"
    )
    position: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[MilestoneStatus] = mapped_column(
        str_enum(MilestoneStatus, "milestone_status"), default=MilestoneStatus.TODO
    )
    target_date: Mapped[date | None] = mapped_column(Date)
