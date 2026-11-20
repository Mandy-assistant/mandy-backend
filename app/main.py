"""Mandy API application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import Settings, get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.core.middleware import RequestContextMiddleware, SecurityHeadersMiddleware
from app.core.redis import close_redis
from app.db.session import engine
from app.features.health.router import router as health_router

API_PREFIX = "/api/v1"

DESCRIPTION = """
Mandy is a single-owner career assistant: job tracker, learning roadmaps, study tasks,
resumes, tech news and a Gemini-powered assistant.

**Auth** uses passkeys (WebAuthn) and httpOnly cookies. For Swagger, sign in and paste the
access token into *Authorize* (`Authorization: Bearer <token>`); in local dev you can use
`POST /api/v1/auth/dev-login` when `DEV_LOGIN_ENABLED=true`.

Every error has the shape `{"error": {"code", "message", "details"}}`.
"""

TAGS = [
    {"name": "health", "description": "Service health"},
    {"name": "auth", "description": "Passkey (WebAuthn) auth, recovery codes, sessions"},
    {"name": "profile", "description": "Career profile, experience, education, skills"},
    {"name": "resumes", "description": "Resumes with version history"},
    {"name": "jobs", "description": "Job applications and status history"},
    {"name": "roadmaps", "description": "Learning roadmaps and milestones"},
    {"name": "tasks", "description": "Study to-dos"},
    {"name": "focus", "description": "Focus (pomodoro) sessions"},
    {"name": "news", "description": "Tech news and saved items"},
    {"name": "dashboard", "description": "One-call dashboard summary"},
    {"name": "assistant", "description": "Gemini-powered assistant and AI helpers"},
]


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    get_logger("mandy").info("startup")
    yield
    await close_redis()
    await engine.dispose()
    get_logger("mandy").info("shutdown")


def build_api_router(settings: Settings) -> APIRouter:
    api = APIRouter(prefix=API_PREFIX)
    api.include_router(health_router)
    return api


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)

    app = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        description=DESCRIPTION,
        openapi_tags=TAGS,
        lifespan=lifespan,
        max_body_size=settings.max_body_bytes,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )
    register_exception_handlers(app)

    # Last added = outermost.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )
    app.add_middleware(SecurityHeadersMiddleware, hsts=settings.env == "prod")
    app.add_middleware(RequestContextMiddleware)

    app.include_router(build_api_router(settings))
    return app


app = create_app()
