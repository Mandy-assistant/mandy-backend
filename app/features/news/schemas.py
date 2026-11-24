import uuid
from datetime import datetime

from pydantic import BaseModel

from app.features.news.models import NewsCategory, NewsKind
from app.shared.pagination import Page
from app.shared.schemas import ORMModel, UTCDateTime


class NewsInsightOut(BaseModel):
    relevance: int
    reason: str


class NewsItemOut(ORMModel):
    id: uuid.UUID
    title: str
    source: str
    url: str
    summary: str
    image_url: str | None
    category: NewsCategory
    published_at: UTCDateTime
    kind: NewsKind = NewsKind.ARTICLE
    score: int = 0
    comments: int = 0
    discussion_url: str | None = None
    author: str | None = None
    tags: list[str] = []
    is_saved: bool = False
    is_liked: bool = False
    insight: NewsInsightOut | None = None


class FeedPage(Page[NewsItemOut]):
    personalizing: bool = False
    """True while the AI is still writing 'why it matters' notes; refetch in a few seconds."""


class NewsSourceOut(BaseModel):
    source: str
    count: int
    latest_at: datetime
    preview_image: str | None


class SavedState(BaseModel):
    is_saved: bool


class LikedState(BaseModel):
    is_liked: bool


class RefreshResult(BaseModel):
    added: int
