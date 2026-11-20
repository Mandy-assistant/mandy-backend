import uuid
from datetime import date
from typing import Literal

from pydantic import BaseModel

from app.features.jobs.schemas import JobOut
from app.features.news.schemas import NewsItemOut
from app.features.roadmaps.schemas import MilestoneOut
from app.features.tasks.schemas import TaskOut


class Pipeline(BaseModel):
    saved: int = 0
    applied: int = 0
    interview: int = 0
    offer: int = 0
    rejected: int = 0


class CurrentRoadmap(BaseModel):
    id: uuid.UUID
    title: str
    progress: int
    milestone_index: int
    milestone_count: int
    next_milestone: MilestoneOut | None


class HeatmapDay(BaseModel):
    date: date
    count: int


class Streak(BaseModel):
    current_days: int
    best_days: int
    week_minutes: int
    heatmap: list[HeatmapDay]


class TimelineEntry(BaseModel):
    time: str | None
    title: str
    kind: Literal["study", "job", "practice"]
    done: bool


class DashboardSummary(BaseModel):
    owner_name: str
    active_applications: int
    interviews_this_week: int
    next_interview: JobOut | None
    pipeline: Pipeline
    tasks_due_today: list[TaskOut]
    tasks_due_today_count: int
    overdue_count: int
    completed_today: int
    focus_task: TaskOut | None
    up_next: TaskOut | None
    current_roadmap: CurrentRoadmap | None
    latest_news: list[NewsItemOut]
    streak: Streak
    timeline: list[TimelineEntry]
