import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.core.exceptions import error_responses
from app.db.session import DbSession
from app.features.auth.deps import CurrentUser
from app.features.tasks import service
from app.features.tasks.models import TaskPriority
from app.features.tasks.schemas import TaskCreate, TaskFilter, TaskOut, TaskUpdate
from app.shared.timeutil import UserTZ

router = APIRouter(prefix="/tasks", tags=["tasks"], responses=error_responses(401))


@router.get("", response_model=list[TaskOut], responses=error_responses(422))
async def list_tasks(
    user: CurrentUser,
    db: DbSession,
    tz: UserTZ,
    filter_: Annotated[TaskFilter | None, Query(alias="filter")] = None,
    priority: TaskPriority | None = None,
    roadmap_id: uuid.UUID | None = None,
    milestone_id: uuid.UUID | None = None,
) -> list[TaskOut]:
    tasks = await service.list_tasks(
        db,
        user.id,
        flt=filter_,
        priority=priority,
        roadmap_id=roadmap_id,
        milestone_id=milestone_id,
        tz=tz,
    )
    return [TaskOut.model_validate(t) for t in tasks]


@router.post(
    "",
    response_model=TaskOut,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(404, 422),
)
async def create_task(body: TaskCreate, user: CurrentUser, db: DbSession) -> TaskOut:
    return TaskOut.model_validate(await service.create_task(db, user.id, body))


@router.patch("/{task_id}", response_model=TaskOut, responses=error_responses(404, 422))
async def update_task(
    task_id: uuid.UUID, body: TaskUpdate, user: CurrentUser, db: DbSession
) -> TaskOut:
    return TaskOut.model_validate(await service.update_task(db, task_id, user.id, body))


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT, responses=error_responses(404))
async def delete_task(task_id: uuid.UUID, user: CurrentUser, db: DbSession) -> None:
    await service.delete_task(db, task_id, user.id)


@router.post("/{task_id}/complete", response_model=TaskOut, responses=error_responses(404))
async def complete_task(task_id: uuid.UUID, user: CurrentUser, db: DbSession) -> TaskOut:
    return TaskOut.model_validate(await service.set_done(db, task_id, user.id, True))


@router.post("/{task_id}/reopen", response_model=TaskOut, responses=error_responses(404))
async def reopen_task(task_id: uuid.UUID, user: CurrentUser, db: DbSession) -> TaskOut:
    return TaskOut.model_validate(await service.set_done(db, task_id, user.id, False))
