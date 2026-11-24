"""Common schema helpers."""

from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, PlainSerializer

from app.shared.timeutil import ensure_utc, to_utc_iso


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


UTCDateTime = Annotated[datetime, PlainSerializer(to_utc_iso, return_type=str, when_used="json")]

# Input datetimes: naive values are treated as UTC; aware values are converted to UTC.
UTCInput = Annotated[datetime, AfterValidator(ensure_utc)]
