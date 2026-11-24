import uuid
from typing import Literal

from pydantic import BaseModel, Field


class AssistantStatus(BaseModel):
    enabled: bool
    model: str


class HistoryTurn(BaseModel):
    role: Literal["user", "model"]
    content: str = Field(max_length=8000)


class AskIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000, examples=["Add a task to revise CNNs"])
    history: list[HistoryTurn] = Field(default=[], max_length=30)
    tz: str | None = Field(default=None, examples=["Asia/Kolkata"])


class AssistantAction(BaseModel):
    type: Literal["task_created", "job_created", "roadmap_created"]
    id: uuid.UUID
    title: str


class AskOut(BaseModel):
    reply: str = Field(description="Markdown")
    actions: list[AssistantAction]


class RewriteIn(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    kind: Literal["summary", "bullet", "cover_note"]
    instruction: str | None = Field(default=None, max_length=500)


class RewriteOut(BaseModel):
    text: str


# ---- structured output for roadmap generation ------------------------------------------


class PlannedResource(BaseModel):
    title: str
    url: str


class PlannedMilestone(BaseModel):
    title: str
    description: str
    estimated_weeks: int
    resources: list[PlannedResource]


class RoadmapPlan(BaseModel):
    title: str
    goal: str
    milestones: list[PlannedMilestone]
