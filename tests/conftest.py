"""Test setup: separate `mandy_test` database with migrations applied, one rolled-back
transaction per test, Redis db 15 flushed per test, httpx AsyncClient over ASGI."""

import asyncio
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import timedelta

import asyncpg
import pytest
from sqlalchemy.engine import make_url

from app.core.config import Settings, get_settings

_base = Settings()
TEST_DATABASE_URL = _base.test_database_url or make_url(_base.database_url).set(
    database="mandy_test"
).render_as_string(hide_password=False)
TEST_REDIS_URL = _base.test_redis_url or _base.redis_url.rsplit("/", 1)[0] + "/15"

os.environ.update(
    {
        "ENV": "test",
        # The suite exercises the v1 endpoints, whatever API_VERSION the local .env picks.
        "API_VERSION": "v1",
        "DATABASE_URL": TEST_DATABASE_URL,
        "REDIS_URL": TEST_REDIS_URL,
        "GEMINI_API_KEY": "",
        "DEV_LOGIN_ENABLED": "false",
        "NEWS_FEEDS_ENABLED": "false",
        "LOG_LEVEL": "WARNING",
    }
)
get_settings.cache_clear()

import httpx  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncEngine,
    AsyncSession,
    create_async_engine,
)
from sqlalchemy.pool import NullPool  # noqa: E402

from alembic import command  # noqa: E402
from app.core.redis import get_redis  # noqa: E402
from app.core.security import create_token  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.features.auth.models import User  # noqa: E402
from app.main import create_app  # noqa: E402

ClientFactory = Callable[[User | None], Awaitable[httpx.AsyncClient]]


async def _ensure_database(url: str) -> None:
    u = make_url(url)
    conn = await asyncpg.connect(
        user=u.username, password=u.password, host=u.host, port=u.port, database="postgres"
    )
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", u.database)
        if not exists:
            await conn.execute(f'CREATE DATABASE "{u.database}"')
    finally:
        await conn.close()


def _alembic_config() -> Config:
    cfg = Config("alembic.ini")
    cfg.attributes["database_url"] = TEST_DATABASE_URL
    cfg.attributes["configure_logger"] = False
    return cfg


@pytest.fixture(scope="session")
async def engine() -> AsyncIterator[AsyncEngine]:
    await _ensure_database(TEST_DATABASE_URL)
    await asyncio.to_thread(command.upgrade, _alembic_config(), "head")
    eng = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    yield eng
    await eng.dispose()


@pytest.fixture
async def db(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    async with engine.connect() as conn:
        trans = await conn.begin()
        session = AsyncSession(
            bind=conn,
            expire_on_commit=False,
            autoflush=False,
            join_transaction_mode="create_savepoint",
        )
        try:
            yield session
        finally:
            await session.close()
            await trans.rollback()


@pytest.fixture(autouse=True)
async def _flush_redis() -> AsyncIterator[None]:
    await get_redis().flushdb()
    yield


@pytest.fixture(scope="session")
def app():  # type: ignore[no-untyped-def]
    return create_app()


@pytest.fixture
def settings() -> Settings:
    return get_settings()


@pytest.fixture
async def make_client(app, db: AsyncSession) -> AsyncIterator[ClientFactory]:  # type: ignore[no-untyped-def]
    async def override_db() -> AsyncIterator[AsyncSession]:
        yield db

    app.dependency_overrides[get_db] = override_db
    clients: list[httpx.AsyncClient] = []

    async def factory(user: User | None = None, target_app=None) -> httpx.AsyncClient:  # type: ignore[no-untyped-def]
        target = target_app or app
        target.dependency_overrides[get_db] = override_db
        headers = {}
        if user is not None:
            token = create_token(user.id, "access", timedelta(minutes=15)).token
            headers["Authorization"] = f"Bearer {token}"
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=target),
            base_url=f"http://test{get_settings().api_prefix}",
            headers=headers,
        )
        clients.append(client)
        return client

    yield factory
    for c in clients:
        await c.aclose()
    app.dependency_overrides.clear()


async def _create_user(db: AsyncSession, email: str, name: str) -> User:
    user = User(email=email, display_name=name)
    db.add(user)
    await db.commit()
    return user


@pytest.fixture
async def user(db: AsyncSession) -> User:
    return await _create_user(db, "owner@example.com", "Owner")


@pytest.fixture
async def other_user(db: AsyncSession, user: User) -> User:
    return await _create_user(db, "other@example.com", "Other")


@pytest.fixture
async def client(make_client: ClientFactory) -> httpx.AsyncClient:
    return await make_client(None)


@pytest.fixture
async def auth_client(make_client: ClientFactory, user: User) -> httpx.AsyncClient:
    return await make_client(user)


@pytest.fixture
async def other_user_client(make_client: ClientFactory, other_user: User) -> httpx.AsyncClient:
    return await make_client(other_user)
