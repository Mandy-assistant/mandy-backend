import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    ARRAY,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPrimaryKey, str_enum


class NewsCategory(enum.StrEnum):
    AI = "ai"
    WEB = "web"
    CLOUD = "cloud"
    DATA = "data"
    SECURITY = "security"
    DEV = "dev"
    MOBILE = "mobile"
    CAREER = "career"


class NewsKind(enum.StrEnum):
    ARTICLE = "article"
    DISCUSSION = "discussion"
    REPO = "repo"
    LAUNCH = "launch"


class InteractionKind(enum.StrEnum):
    OPEN = "open"
    LIKE = "like"
    HIDE = "hide"


class NewsItem(UUIDPrimaryKey, Timestamps, Base):
    """Shared across users."""

    __tablename__ = "news_items"

    title: Mapped[str] = mapped_column(String(500))
    source: Mapped[str] = mapped_column(String(100), index=True)
    url: Mapped[str] = mapped_column(String(1000), unique=True)
    summary: Mapped[str] = mapped_column(Text, default="", server_default="")
    image_url: Mapped[str | None] = mapped_column(String(1000))
    category: Mapped[NewsCategory] = mapped_column(
        str_enum(NewsCategory, "news_category"), index=True
    )
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    kind: Mapped[NewsKind] = mapped_column(
        str_enum(NewsKind, "news_kind"), default=NewsKind.ARTICLE, server_default="article"
    )
    score: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    comments: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    discussion_url: Mapped[str | None] = mapped_column(String(1000))
    author: Mapped[str | None] = mapped_column(String(200))
    tags: Mapped[list[str]] = mapped_column(ARRAY(String(50)), default=list, server_default="{}")


class SavedNews(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "saved_news"
    __table_args__ = (UniqueConstraint("user_id", "news_item_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    news_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("news_items.id", ondelete="CASCADE"), index=True
    )


class NewsInteraction(UUIDPrimaryKey, Timestamps, Base):
    """What the user did with an item: opened, liked or hid it. Feeds the interest profile."""

    __tablename__ = "news_interactions"
    __table_args__ = (UniqueConstraint("user_id", "news_item_id", "kind"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    news_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("news_items.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[InteractionKind] = mapped_column(str_enum(InteractionKind, "interaction_kind"))


class NewsInsight(UUIDPrimaryKey, Timestamps, Base):
    """The AI's per-user take on an item: how relevant it is and why."""

    __tablename__ = "news_insights"
    __table_args__ = (UniqueConstraint("user_id", "news_item_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    news_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("news_items.id", ondelete="CASCADE"), index=True
    )
    relevance: Mapped[int] = mapped_column(SmallInteger)
    reason: Mapped[str] = mapped_column(String(300), default="", server_default="")
