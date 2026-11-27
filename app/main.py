from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from app.db.session import engine
from app.features.health.router import router as health_router
from app.features.auth.route import auth_router


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await engine.dispose()


app = FastAPI(title="Mandy API", version="0.1.0", lifespan=lifespan)
app.include_router(health_router)
app.include_router(auth_router)