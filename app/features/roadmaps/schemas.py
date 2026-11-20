import uuid
from datetime import date

from pydantic import BaseModel, Field

from app.features.roadmaps.models import MilestoneStatus, RoadmapStatus
from app.shared.schemas import ORMModel, UTCDateTime


class Resource(BaseModel):
    title: str = Field(max_length=200)
    url: str = Field(max_length=1000)


class MilestoneCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None
    resources: list[Resource] = Field(default=[], max_length=30)
    status: MilestoneStatus = MilestoneStatus.TODO
    target_date: date | None = None
    position: int | None = Field(default=None, ge=0)


class MilestoneUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    resources: list[Resource] | None = Field(default=None, max_length=30)
    status: MilestoneStatus | None = None
    target_date: date | None = None


class MilestoneOut(ORMModel):
    id: uuid.UUID
    roadmap_id: uuid.UUID
    title: str
    description: str | None
    resources: list[Resource]
    position: int
    status: MilestoneStatus
    target_date: date | None
    task_count: int = 0
    done_task_count: int = 0


class RoadmapCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200, examples=["ML Engineer"])
    goal: str | None = None
    status: RoadmapStatus = RoadmapStatus.ACTIVE
    target_date: date | None = None
    milestones: list[MilestoneCreate] = Field(default=[], max_length=50)


class RoadmapUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    goal: str | None = None
    status: RoadmapStatus | None = None
    target_date: date | None = None


class RoadmapOut(ORMModel):
    id: uuid.UUID
    title: str
    goal: str | None
    status: RoadmapStatus
    target_date: date | None
    progress: int = Field(ge=0, le=100)
    milestone_count: int
    done_count: int
    created_at: UTCDateTime
    updated_at: UTCDateTime


class RoadmapDetail(RoadmapOut):
    milestones: list[MilestoneOut]


class MilestoneOrder(BaseModel):
    ids: list[uuid.UUID]


class RoadmapGenerate(BaseModel):
    goal: str = Field(min_length=3, max_length=500, examples=["Become an ML engineer"])
    target_date: date | None = None
    hours_per_week: int | None = Field(default=None, ge=1, le=80)
