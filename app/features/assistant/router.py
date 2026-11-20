from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.ai import AIClient, get_ai_client
from app.core.config import get_settings
from app.core.exceptions import error_responses
from app.db.session import DbSession
from app.features.assistant import service
from app.features.assistant.schemas import AskIn, AskOut, AssistantStatus, RewriteIn, RewriteOut
from app.features.auth.deps import CurrentUser
from app.features.roadmaps.schemas import RoadmapDetail, RoadmapGenerate

router = APIRouter(tags=["assistant"], responses=error_responses(401))

AI = Annotated[AIClient, Depends(get_ai_client)]
AI_ERRORS = error_responses(422, 429, 502, 503)


@router.get("/assistant/status", response_model=AssistantStatus)
async def status(_: CurrentUser) -> AssistantStatus:
    settings = get_settings()
    return AssistantStatus(enabled=settings.ai_enabled, model=settings.gemini_model)


@router.post(
    "/assistant/ask",
    response_model=AskOut,
    summary="Chat with Mandy (can create tasks and jobs for you)",
    responses=AI_ERRORS,
)
async def ask(body: AskIn, user: CurrentUser, db: DbSession, ai: AI) -> AskOut:
    return await service.ask(db, user, ai, body)


@router.post(
    "/ai/rewrite",
    response_model=RewriteOut,
    summary="Rewrite resume text (summary, bullet or cover note)",
    responses=AI_ERRORS,
)
async def rewrite(body: RewriteIn, _: CurrentUser, ai: AI) -> RewriteOut:
    return RewriteOut(text=await service.rewrite(ai, body))


@router.post(
    "/roadmaps/generate",
    response_model=RoadmapDetail,
    status_code=201,
    tags=["roadmaps"],
    summary="Let Gemini plan a roadmap (4-8 milestones with resources) and save it",
    responses=AI_ERRORS,
)
async def generate_roadmap(
    body: RoadmapGenerate, user: CurrentUser, db: DbSession, ai: AI
) -> RoadmapDetail:
    return await service.generate_roadmap(db, user, ai, body)
