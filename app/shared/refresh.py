"""Pull-on-visit scheduling: Render's free tier has no cron, so a visit triggers a due refresh."""

from app.core.logging import get_logger
from app.core.redis import get_redis

log = get_logger(__name__)


async def claim(name: str, every_minutes: int) -> bool:
    """True for exactly one caller per period (a Redis SET NX with expiry)."""
    try:
        return bool(await get_redis().set(f"refresh:{name}", "1", ex=every_minutes * 60, nx=True))
    except Exception as exc:
        log.warning("refresh_claim_failed", name=name, error=type(exc).__name__)
        return False


async def release(name: str) -> None:
    """Let the next visit try again (used when a refresh failed)."""
    try:
        await get_redis().delete(f"refresh:{name}")
    except Exception as exc:
        log.warning("refresh_release_failed", name=name, error=type(exc).__name__)
