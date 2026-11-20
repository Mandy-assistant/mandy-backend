"""Timezone helpers (all storage is UTC; `tz` query params pick the user's local day)."""

from datetime import UTC, date, datetime, time, timedelta
from functools import cache
from importlib import resources
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import Depends, Query

from app.core.exceptions import ValidationFailed


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def to_utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


@cache
def _tz_links() -> dict[str, str]:
    """Legacy alias -> canonical IANA name (Asia/Calcutta -> Asia/Kolkata), from tzdata."""
    try:
        text = resources.files("tzdata").joinpath("zoneinfo/tzdata.zi").read_text()
    except (FileNotFoundError, ModuleNotFoundError):
        return {}
    links: dict[str, str] = {}
    for line in text.splitlines():
        if line.startswith("L "):
            _, target, alias = line.split()[:3]
            links[alias] = target
    # Links can chain; resolve to the final zone.
    for alias, target in links.items():
        while target in links:
            target = links[target]
        links[alias] = target
    return links


def canonical_tz_name(name: str) -> str:
    return _tz_links().get(name, name)


def parse_tz(name: str | None) -> ZoneInfo:
    """Browsers still report legacy names (Chrome: "Asia/Calcutta"). Python accepts them but
    Postgres may not, and the name is passed into SQL, so always return the canonical zone."""
    try:
        return ZoneInfo(canonical_tz_name(name or "UTC"))
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValidationFailed("tz", f"Unknown timezone: {name}") from exc


def tz_param(
    tz: Annotated[
        str, Query(description="IANA timezone, e.g. Asia/Kolkata", examples=["Asia/Kolkata"])
    ] = "UTC",
) -> ZoneInfo:
    return parse_tz(tz)


UserTZ = Annotated[ZoneInfo, Depends(tz_param)]


def now_utc() -> datetime:
    return datetime.now(UTC)


def local_today(tz: ZoneInfo) -> date:
    return datetime.now(tz).date()


def day_bounds_utc(day: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """[start, end) of a local calendar day, as UTC datetimes."""
    start = datetime.combine(day, time.min, tzinfo=tz)
    end = start + timedelta(days=1)
    return start.astimezone(UTC), end.astimezone(UTC)


def week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())
