"""Common schema helpers."""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, PlainSerializer

from app.shared.timeutil import to_utc_iso


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


UTCDateTime = Annotated[datetime, PlainSerializer(to_utc_iso, return_type=str, when_used="json")]
