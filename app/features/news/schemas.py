import uuid

from pydantic import BaseModel

from app.features.news.models import NewsCategory
from app.shared.schemas import ORMModel, UTCDateTime


class NewsItemOut(ORMModel):
    id: uuid.UUID
    title: str
    source: str
    url: str
    summary: str
    image_url: str | None
    category: NewsCategory
    published_at: UTCDateTime
    is_saved: bool = False


class SavedState(BaseModel):
    is_saved: bool


class RefreshResult(BaseModel):
    added: int
