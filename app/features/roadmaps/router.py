import uuid

from fastapi import APIRouter, status

from app.core.exceptions import error_responses
from app.db.session import DbSession
from app.features.auth.deps import CurrentUser
from app.features.roadmaps import service
from app.features.roadmaps.schemas import (
    MilestoneCreate,
    MilestoneOrder,
    MilestoneOut,
    MilestoneUpdate,
    RoadmapCreate,
    RoadmapDetail,
    RoadmapOut,
    RoadmapUpdate,
)

router = APIRouter(tags=["roadmaps"], responses=error_responses(401))


@router.get("/roadmaps", response_model=list[RoadmapOut])
async def list_roadmaps(user: CurrentUser, db: DbSession) -> list[RoadmapOut]:
    return await service.list_roadmaps(db, user.id)


@router.post(
    "/roadmaps",
    response_model=RoadmapDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Create a roadmap (optionally with milestones)",
    responses=error_responses(422),
)
async def create_roadmap(body: RoadmapCreate, user: CurrentUser, db: DbSession) -> RoadmapDetail:
    return await service.create_roadmap(db, user.id, body)


@router.get("/roadmaps/{roadmap_id}", response_model=RoadmapDetail, responses=error_responses(404))
async def get_roadmap(roadmap_id: uuid.UUID, user: CurrentUser, db: DbSession) -> RoadmapDetail:
    return await service.get_detail(db, roadmap_id, user.id)


@router.patch(
    "/roadmaps/{roadmap_id}", response_model=RoadmapDetail, responses=error_responses(404, 422)
)
async def update_roadmap(
    roadmap_id: uuid.UUID, body: RoadmapUpdate, user: CurrentUser, db: DbSession
) -> RoadmapDetail:
    return await service.update_roadmap(db, roadmap_id, user.id, body)


@router.delete(
    "/roadmaps/{roadmap_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a roadmap (milestones cascade; linked tasks are kept, unlinked)",
    responses=error_responses(404),
)
async def delete_roadmap(roadmap_id: uuid.UUID, user: CurrentUser, db: DbSession) -> None:
    await service.delete_roadmap(db, roadmap_id, user.id)


@router.post(
    "/roadmaps/{roadmap_id}/milestones",
    response_model=MilestoneOut,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(404, 422),
)
async def add_milestone(
    roadmap_id: uuid.UUID, body: MilestoneCreate, user: CurrentUser, db: DbSession
) -> MilestoneOut:
    return await service.add_milestone(db, roadmap_id, user.id, body)


@router.put(
    "/roadmaps/{roadmap_id}/milestones/order",
    response_model=RoadmapDetail,
    summary="Reorder milestones atomically (ids must match the roadmap's milestones exactly)",
    responses=error_responses(404, 422),
)
async def reorder_milestones(
    roadmap_id: uuid.UUID, body: MilestoneOrder, user: CurrentUser, db: DbSession
) -> RoadmapDetail:
    return await service.reorder(db, roadmap_id, user.id, body.ids)


@router.patch(
    "/milestones/{milestone_id}", response_model=MilestoneOut, responses=error_responses(404, 422)
)
async def update_milestone(
    milestone_id: uuid.UUID, body: MilestoneUpdate, user: CurrentUser, db: DbSession
) -> MilestoneOut:
    return await service.update_milestone(db, milestone_id, user.id, body)


@router.delete(
    "/milestones/{milestone_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=error_responses(404),
)
async def delete_milestone(milestone_id: uuid.UUID, user: CurrentUser, db: DbSession) -> None:
    await service.delete_milestone(db, milestone_id, user.id)
