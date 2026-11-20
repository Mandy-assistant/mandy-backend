"""Per-user dashboard cache. Writers call `invalidate_dashboard` after changing data."""

import uuid

from app.core.redis import bump_version, cache_version


def _scope(user_id: uuid.UUID) -> str:
    return f"dashboard:{user_id}"


async def dashboard_cache_key(user_id: uuid.UUID, tz: str) -> str:
    version = await cache_version(_scope(user_id))
    return f"cache:dashboard:{user_id}:v{version}:{tz}"


async def invalidate_dashboard(user_id: uuid.UUID) -> None:
    await bump_version(_scope(user_id))
