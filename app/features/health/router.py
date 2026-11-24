from typing import Literal

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text

from app.core.redis import get_redis
from app.db.session import DbSession

router = APIRouter(tags=["health"])

Status = Literal["ok", "error"]


class HealthOut(BaseModel):
    status: Status
    db: Status
    redis: Status


@router.get(
    "/health",
    response_model=HealthOut,
    summary="Liveness/readiness of the API, Postgres and Redis",
    responses={503: {"model": HealthOut, "description": "A dependency is down"}},
)
async def health(db: DbSession) -> JSONResponse:
    db_status: Status = "ok"
    redis_status: Status = "ok"
    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        db_status = "error"
    try:
        await get_redis().ping()
    except Exception:
        redis_status = "error"
    ok = db_status == "ok" and redis_status == "ok"
    body = HealthOut(status="ok" if ok else "error", db=db_status, redis=redis_status)
    return JSONResponse(body.model_dump(), status_code=200 if ok else 503)
