import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Response, status

from app.core.ai import AIClient, get_optional_ai_client
from app.core.config import get_settings
from app.core.exceptions import error_responses
from app.db.session import DbSession
from app.features.auth.deps import CurrentUser
from app.features.discover import service
from app.features.discover.providers import AllJobBoardsProvider, JobsProvider, NullJobsProvider
from app.features.discover.schemas import DiscoverPage, DiscoverRefreshResult, Region
from app.features.jobs.schemas import JobOut
from app.shared import refresh as scheduler
from app.shared.pagination import Pagination

# Registered before the jobs router so /jobs/discover isn't read as /jobs/{job_id}.
router = APIRouter(prefix="/jobs/discover", tags=["discover"], responses=error_responses(401))

OptionalAI = Annotated[AIClient | None, Depends(get_optional_ai_client)]


def get_jobs_provider() -> JobsProvider:
    return AllJobBoardsProvider() if get_settings().news_feeds_enabled else NullJobsProvider()


Provider = Annotated[JobsProvider, Depends(get_jobs_provider)]


@router.get(
    "",
    response_model=DiscoverPage,
    summary="Openings from public job boards, ranked for you, with an AI fit check",
)
async def discover(
    user: CurrentUser,
    db: DbSession,
    pagination: Pagination,
    tasks: BackgroundTasks,
    provider: Provider,
    ai: OptionalAI,
    region: Annotated[Region | None, Query(description="Defaults to your saved regions")] = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
) -> DiscoverPage:
    settings = get_settings()
    if settings.news_feeds_enabled and await scheduler.claim("jobs", settings.jobs_refresh_minutes):
        tasks.add_task(service.run_refresh, provider)
    personalizing = False
    if (
        ai is not None
        and pagination.page == 1
        and not q
        and await service.needs_fit(db, user.id, region)
        and await service.claim_fit_run(user.id)
    ):
        tasks.add_task(service.run_fits, user.id, ai, region)
        personalizing = True
    return await service.discover(db, user.id, pagination, region, q, personalizing)


@router.post(
    "/{posting_id}/track",
    response_model=JobOut,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(404),
    summary="Add the opening to your job tracker",
)
async def track(posting_id: uuid.UUID, user: CurrentUser, db: DbSession) -> JobOut:
    return JobOut.model_validate(await service.track(db, user.id, posting_id))


@router.put("/{posting_id}/hide", status_code=204, responses=error_responses(404))
async def hide(posting_id: uuid.UUID, user: CurrentUser, db: DbSession) -> Response:
    await service.set_hidden(db, user.id, posting_id, True)
    return Response(status_code=204)


@router.delete("/{posting_id}/hide", status_code=204, responses=error_responses(404))
async def unhide(posting_id: uuid.UUID, user: CurrentUser, db: DbSession) -> Response:
    await service.set_hidden(db, user.id, posting_id, False)
    return Response(status_code=204)


@router.post("/refresh", response_model=DiscoverRefreshResult, summary="Pull job boards now")
async def refresh(_: CurrentUser, db: DbSession, provider: Provider) -> DiscoverRefreshResult:
    return DiscoverRefreshResult(added=await service.refresh(db, provider))
