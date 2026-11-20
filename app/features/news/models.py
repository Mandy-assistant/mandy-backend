import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPrimaryKey, str_enum


class NewsCategory(enum.StrEnum):
    AI = "ai"
    WEB = "web"
    CLOUD = "cloud"
    DATA = "data"
    SECURITY = "security"


class NewsItem(UUIDPrimaryKey, Timestamps, Base):
    """Shared across users."""

    __tablename__ = "news_items"

    title: Mapped[str] = mapped_column(String(500))
    source: Mapped[str] = mapped_column(String(100))
    url: Mapped[str] = mapped_column(String(1000), unique=True)
    summary: Mapped[str] = mapped_column(Text, default="", server_default="")
    image_url: Mapped[str | None] = mapped_column(String(1000))
    category: Mapped[NewsCategory] = mapped_column(
        str_enum(NewsCategory, "news_category"), index=True
    )
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class SavedNews(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "saved_news"
    __table_args__ = (UniqueConstraint("user_id", "news_item_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    news_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("news_items.id", ondelete="CASCADE"), index=True
    )
