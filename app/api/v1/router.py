"""Routes served by API v1 (mounted at `/api/v1` when `API_VERSION=v1`)."""

from fastapi import APIRouter

from app.core.config import Settings
from app.features.assistant.router import router as assistant_router
from app.features.auth.router import dev_router as auth_dev_router
from app.features.auth.router import router as auth_router
from app.features.dashboard.router import router as dashboard_router
from app.features.discover.router import router as discover_router
from app.features.focus.router import router as focus_router
from app.features.health.router import router as health_router
from app.features.jobs.router import router as jobs_router
from app.features.news.router import router as news_router
from app.features.personalize.router import router as interests_router
from app.features.profile.router import router as profile_router
from app.features.resumes.router import router as resumes_router
from app.features.roadmaps.router import router as roadmaps_router
from app.features.tasks.router import router as tasks_router


def build_router(settings: Settings) -> APIRouter:
    router = APIRouter()
    router.include_router(health_router)
    router.include_router(auth_router)
    router.include_router(profile_router)
    router.include_router(resumes_router)
    router.include_router(discover_router)  # before jobs: owns /jobs/discover
    router.include_router(jobs_router)
    router.include_router(assistant_router)  # before roadmaps: owns POST /roadmaps/generate
    router.include_router(roadmaps_router)
    router.include_router(tasks_router)
    router.include_router(focus_router)
    router.include_router(news_router)
    router.include_router(interests_router)
    router.include_router(dashboard_router)
    if settings.dev_login_active:
        router.include_router(auth_dev_router)
    return router
