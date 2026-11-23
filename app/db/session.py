"""Async engine, session factory and the `get_db` dependency."""

from collections.abc import AsyncIterator
from typing import Annotated, Any
from uuid import uuid4

from fastapi import Depends
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings

_settings = get_settings()

# Behind PgBouncer (Neon's pooled host) a backend connection can change between statements, so
# asyncpg must not cache prepared statements under fixed names.
_connect_args: dict[str, Any] = (
    {
        "statement_cache_size": 0,
        "prepared_statement_name_func": lambda: f"__asyncpg_{uuid4()}__",
    }
    if _settings.uses_connection_pooler
    else {}
)

engine: AsyncEngine = create_async_engine(
    _settings.database_url,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=10,
    # Neon suspends idle computes and drops their connections; recycle before that bites.
    pool_recycle=300,
    connect_args=_connect_args,
)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


DbSession = Annotated[AsyncSession, Depends(get_db)]
