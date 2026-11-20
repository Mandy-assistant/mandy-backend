"""Shared async Redis client plus small, failure-tolerant cache helpers."""

import json
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)

_client: Redis | None = None


def get_redis() -> Redis:
    """Return the process-wide Redis client (created lazily, closed in the app lifespan)."""
    global _client
    if _client is None:
        _client = Redis.from_url(get_settings().redis_url, decode_responses=True)
    return _client


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def cache_get(key: str) -> Any | None:
    try:
        raw = await get_redis().get(key)
    except RedisError as exc:
        log.warning("cache_get_failed", key=key, error=str(exc))
        return None
    return json.loads(raw) if raw else None


async def cache_set(key: str, value: Any, ttl_seconds: int) -> None:
    try:
        await get_redis().set(key, json.dumps(value, default=str), ex=ttl_seconds)
    except RedisError as exc:
        log.warning("cache_set_failed", key=key, error=str(exc))


async def cache_version(name: str) -> int:
    """A counter used to namespace cache keys; bumping it invalidates them all."""
    try:
        raw = await get_redis().get(f"ver:{name}")
    except RedisError:
        return 0
    return int(raw) if raw else 0


async def bump_version(name: str) -> None:
    try:
        await get_redis().incr(f"ver:{name}")
    except RedisError as exc:
        log.warning("cache_bump_failed", name=name, error=str(exc))
