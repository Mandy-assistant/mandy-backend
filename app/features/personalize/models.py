import enum
import uuid
from typing import Any

from sqlalchemy import ARRAY, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPrimaryKey, str_enum


class SearchScope(enum.StrEnum):
    NEWS = "news"
    JOBS = "jobs"


class InterestProfile(UUIDPrimaryKey, Timestamps, Base):
    """What Mandy knows the user cares about: explicit follows/mutes plus learned weights."""

    __tablename__ = "interest_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )
    followed: Mapped[list[str]] = mapped_column(
        ARRAY(String(50)), default=list, server_default="{}"
    )
    muted: Mapped[list[str]] = mapped_column(ARRAY(String(50)), default=list, server_default="{}")
    # remote | india | anywhere
    job_regions: Mapped[list[str]] = mapped_column(
        ARRAY(String(20)), default=list, server_default="{}"
    )
    # term -> weight, recomputed from activity (cached here so ranking doesn't rebuild it)
    learned: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")


class SearchEvent(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "search_events"
    __table_args__ = (Index("ix_search_events_user_id_created_at", "user_id", "created_at"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    scope: Mapped[SearchScope] = mapped_column(str_enum(SearchScope, "search_scope"))
    query: Mapped[str] = mapped_column(String(100))
