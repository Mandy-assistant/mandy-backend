"""Routes served by API v2 (mounted at `/api/v2` when `API_VERSION=v2`).

v2 starts empty; endpoints are added here one by one. For a feature that changes in v2, add a
v2 router next to it (e.g. `app/features/jobs/router_v2.py` + `schemas_v2.py`, using the same
`service.py`) and include it below. A feature router that v2 serves unchanged can be included
as-is from `app/features/<name>/router.py`.
"""

from fastapi import APIRouter

from app.core.config import Settings


def build_router(settings: Settings) -> APIRouter:
    router = APIRouter()
    return router
