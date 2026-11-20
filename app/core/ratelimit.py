"""Fixed-window rate limiting in Redis (per bucket, per client IP)."""

import time
from collections.abc import Awaitable, Callable

from fastapi import Request
from redis.exceptions import RedisError

from app.core.config import get_settings
from app.core.exceptions import RateLimitedError
from app.core.redis import get_redis

WINDOW_SECONDS = 60


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def rate_limit(bucket: str) -> Callable[[Request], Awaitable[None]]:
    """Dependency factory: N requests / minute / IP for `bucket` → 429 RATE_LIMITED."""

    async def dependency(request: Request) -> None:
        limit = get_settings().rate_limit_per_minute
        window = int(time.time() // WINDOW_SECONDS)
        key = f"rl:{bucket}:{client_ip(request)}:{window}"
        try:
            redis = get_redis()
            count = await redis.incr(key)
            if count == 1:
                await redis.expire(key, WINDOW_SECONDS)
        except RedisError:
            return  # fail open: an unavailable cache must not lock the owner out
        if count > limit:
            retry = WINDOW_SECONDS - int(time.time()) % WINDOW_SECONDS
            raise RateLimitedError(headers={"Retry-After": str(retry)})

    return dependency
