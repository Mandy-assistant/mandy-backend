import uuid

from pydantic import BaseModel, Field, model_validator

from app.shared.schemas import ORMModel, UTCDateTime, UTCInput


class FocusSessionCreate(BaseModel):
    task_id: uuid.UUID | None = None
    duration_minutes: int = Field(ge=1, le=600, examples=[25])
    started_at: UTCInput
    ended_at: UTCInput

    @model_validator(mode="after")
    def _order(self) -> "FocusSessionCreate":
        if self.ended_at < self.started_at:
            raise ValueError("ended_at must be after started_at")
        return self


class FocusSessionOut(ORMModel):
    id: uuid.UUID
    task_id: uuid.UUID | None
    duration_minutes: int
    started_at: UTCDateTime
    ended_at: UTCDateTime
