"""Versioned HTTP API.

`API_VERSION` in the environment picks the one version this process serves, mounted at
`/api/<version>`; routes of any other version are not registered (they 404 and are absent
from `/openapi.json`).

Each version lives in its own package (`app/api/v1/`, later `app/api/v2/`) that decides which
routers it exposes. Features (`app/features/<name>/`) keep the services, models and the routers
they already have, so a new version only adds routers/schemas for what actually changes.

To add a version: create `app/api/vN/` with a `build_router(settings)`, register it in
`VERSIONS` below and add `"vN"` to `ApiVersion` in `app/core/config.py`.
"""

from collections.abc import Callable

from fastapi import APIRouter

from app.api import v1
from app.core.config import Settings

VERSIONS: dict[str, Callable[[Settings], APIRouter]] = {
    "v1": v1.build_router,
}


def build_api_router(settings: Settings) -> APIRouter:
    """Router for `settings.api_version`, mounted under its `/api/<version>` prefix."""
    build = VERSIONS.get(settings.api_version)
    if build is None:
        raise RuntimeError(
            f"API_VERSION={settings.api_version!r} has no router; "
            f"available: {', '.join(sorted(VERSIONS))}"
        )
    api = APIRouter(prefix=settings.api_prefix)
    api.include_router(build(settings))
    return api
