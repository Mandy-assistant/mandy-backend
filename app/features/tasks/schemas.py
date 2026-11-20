import uuid
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from app.features.tasks.models import TaskPriority, TaskStatus
from app.shared.schemas import ORMModel, UTCDateTime

TaskFilter = Literal["today", "upcoming", "overdue", "completed"]


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300, examples=["Finish CNN chapter"])
    description: str | None = None
    due_date: date | None = None
    priority: TaskPriority = TaskPriority.MEDIUM
    roadmap_id: uuid.UUID | None = None
    milestone_id: uuid.UUID | None = None


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = None
    due_date: date | None = None
    priority: TaskPriority | None = None
    roadmap_id: uuid.UUID | None = None
    milestone_id: uuid.UUID | None = None


class TaskOut(ORMModel):
    id: uuid.UUID
    title: str
    description: str | None
    due_date: date | None
    priority: TaskPriority
    status: TaskStatus
    completed_at: UTCDateTime | None
    roadmap_id: uuid.UUID | None
    milestone_id: uuid.UUID | None
    roadmap_title: str | None
    milestone_title: str | None
    created_at: UTCDateTime
    updated_at: UTCDateTime
