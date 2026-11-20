from fastapi import APIRouter

from app.core.exceptions import error_responses
from app.db.session import DbSession
from app.features.auth.deps import CurrentUser
from app.features.dashboard import service
from app.features.dashboard.schemas import DashboardSummary
from app.shared.timeutil import UserTZ

router = APIRouter(prefix="/dashboard", tags=["dashboard"], responses=error_responses(401))


@router.get(
    "/summary",
    response_model=DashboardSummary,
    summary="Everything the dashboard needs in one call (cached 60 s per user)",
    responses=error_responses(422),
)
async def summary(user: CurrentUser, db: DbSession, tz: UserTZ) -> DashboardSummary:
    return await service.get_summary(db, user, tz)
