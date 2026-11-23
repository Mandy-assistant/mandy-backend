from fastapi import APIRouter

from app.core.exceptions import error_responses
from app.db.session import DbSession
from app.features.auth.deps import CurrentUser
from app.features.personalize import service
from app.features.personalize.schemas import InterestsOut, InterestsUpdate, LearnedTerm

router = APIRouter(prefix="/interests", tags=["interests"], responses=error_responses(401))


async def _out(db: DbSession, user: CurrentUser) -> InterestsOut:
    row = await service.get_or_create(db, user.id)
    weights = await service.terms(db, user.id)
    ctx = await service.context(db, user)
    await db.commit()
    return InterestsOut(
        followed=list(row.followed or []),
        muted=list(row.muted or []),
        job_regions=list(row.job_regions or []),
        learned=[LearnedTerm(**t) for t in service.as_list(weights) if t["weight"] > 0],
        context=ctx,
    )


@router.get("", response_model=InterestsOut, summary="What Mandy has learned about you")
async def get_interests(user: CurrentUser, db: DbSession) -> InterestsOut:
    return await _out(db, user)


@router.put("", response_model=InterestsOut, summary="Follow or mute topics, set job regions")
async def update_interests(body: InterestsUpdate, user: CurrentUser, db: DbSession) -> InterestsOut:
    row = await service.get_or_create(db, user.id)
    if body.followed is not None:
        row.followed = body.followed
        row.muted = [m for m in (row.muted or []) if m not in body.followed]
    if body.muted is not None:
        row.muted = body.muted
        row.followed = [f for f in (row.followed or []) if f not in body.muted]
    if body.job_regions is not None:
        row.job_regions = list(dict.fromkeys(body.job_regions))
    await db.commit()
    await service.touch(user.id)
    return await _out(db, user)
