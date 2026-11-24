from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.core.exceptions import error_responses
from app.db.session import DbSession
from app.features.auth.deps import CurrentUser
from app.features.focus import service
from app.features.focus.schemas import FocusSessionCreate, FocusSessionOut
from app.shared.timeutil import UserTZ

router = APIRouter(prefix="/focus", tags=["focus"], responses=error_responses(401))


@router.post(
    "/sessions",
    response_model=FocusSessionOut,
    status_code=status.HTTP_201_CREATED,
    summary="Record a finished focus session",
    responses=error_responses(404, 422),
)
async def create_session(
    body: FocusSessionCreate, user: CurrentUser, db: DbSession
) -> FocusSessionOut:
    return FocusSessionOut.model_validate(await service.create_session(db, user.id, body))


@router.get(
    "/sessions",
    response_model=list[FocusSessionOut],
    summary="Sessions started on a local day (default: today in `tz`)",
    responses=error_responses(422),
)
async def list_sessions(
    user: CurrentUser,
    db: DbSession,
    tz: UserTZ,
    day: Annotated[date | None, Query(alias="date")] = None,
) -> list[FocusSessionOut]:
    sessions = await service.list_sessions(db, user.id, day, tz)
    return [FocusSessionOut.model_validate(s) for s in sessions]
