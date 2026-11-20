"""News providers. `NewsProvider` is the plug-in point; `RSSProvider` pulls public feeds."""

import asyncio
import html
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Protocol

import httpx

from app.core.logging import get_logger
from app.features.news.models import NewsCategory

log = get_logger(__name__)

MAX_FEED_BYTES = 2_000_000
MAX_ITEMS_PER_FEED = 20
SUMMARY_CHARS = 400

ATOM = "{http://www.w3.org/2005/Atom}"
MEDIA = "{http://search.yahoo.com/mrss/}"


@dataclass(frozen=True)
class FeedConfig:
    url: str
    source: str
    category: NewsCategory


@dataclass(frozen=True)
class FetchedNews:
    title: str
    source: str
    url: str
    summary: str
    image_url: str | None
    category: NewsCategory
    published_at: datetime


class NewsProvider(Protocol):
    async def fetch(self) -> list[FetchedNews]:
        """Return fresh items. Must not raise because one source is down."""
        ...


DEFAULT_FEEDS: list[FeedConfig] = [
    FeedConfig("https://blog.google/technology/ai/rss/", "Google AI Blog", NewsCategory.AI),
    FeedConfig("https://huggingface.co/blog/feed.xml", "Hugging Face", NewsCategory.AI),
    FeedConfig("https://web.dev/feed.xml", "web.dev", NewsCategory.WEB),
    FeedConfig("https://www.smashingmagazine.com/feed/", "Smashing Magazine", NewsCategory.WEB),
    FeedConfig("https://aws.amazon.com/blogs/aws/feed/", "AWS News Blog", NewsCategory.CLOUD),
    FeedConfig("https://blog.cloudflare.com/rss/", "Cloudflare Blog", NewsCategory.CLOUD),
    FeedConfig("https://www.kdnuggets.com/feed", "KDnuggets", NewsCategory.DATA),
    FeedConfig("https://krebsonsecurity.com/feed/", "Krebs on Security", NewsCategory.SECURITY),
    FeedConfig(
        "https://feeds.feedburner.com/TheHackersNews", "The Hacker News", NewsCategory.SECURITY
    ),
]

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_IMG_RE = re.compile(r"<img[^>]+src=[\"']([^\"']+)[\"']", re.IGNORECASE)


def clean_text(raw: str | None, limit: int = SUMMARY_CHARS) -> str:
    if not raw:
        return ""
    text = _WS_RE.sub(" ", html.unescape(_TAG_RE.sub(" ", raw))).strip()
    return text if len(text) <= limit else text[: limit - 1].rsplit(" ", 1)[0] + "…"


def parse_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    raw = raw.strip()
    try:
        dt = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def _text(el: ET.Element | None) -> str | None:
    return el.text.strip() if el is not None and el.text else None


def _image(item: ET.Element, description: str | None) -> str | None:
    for tag in (f"{MEDIA}content", f"{MEDIA}thumbnail", "enclosure"):
        for el in item.iter(tag):
            url = el.get("url")
            if url and (tag != "enclosure" or (el.get("type") or "").startswith("image")):
                return url
    if description:
        match = _IMG_RE.search(description)
        if match:
            return match.group(1)
    return None


def parse_feed(content: bytes, feed: FeedConfig) -> list[FetchedNews]:
    """Parse RSS 2.0 or Atom into items (malformed entries are skipped)."""
    root = ET.fromstring(content)  # noqa: S314
    items: list[FetchedNews] = []
    entries = root.findall("./channel/item") or root.findall(f"{ATOM}entry")
    for entry in entries[:MAX_ITEMS_PER_FEED]:
        if entry.tag == "item":
            title = _text(entry.find("title"))
            link = _text(entry.find("link"))
            description = _text(entry.find("description"))
            published = parse_date(_text(entry.find("pubDate")))
        else:
            title = _text(entry.find(f"{ATOM}title"))
            link_el = entry.find(f"{ATOM}link[@rel='alternate']")
            if link_el is None:
                link_el = entry.find(f"{ATOM}link")
            link = link_el.get("href") if link_el is not None else None
            description = _text(entry.find(f"{ATOM}summary")) or _text(entry.find(f"{ATOM}content"))
            published = parse_date(
                _text(entry.find(f"{ATOM}published")) or _text(entry.find(f"{ATOM}updated"))
            )
        if not title or not link or not link.startswith(("http://", "https://")):
            continue
        items.append(
            FetchedNews(
                title=clean_text(title, 500),
                source=feed.source,
                url=link[:1000],
                summary=clean_text(description),
                image_url=_image(entry, description),
                category=feed.category,
                published_at=published or datetime.now(UTC),
            )
        )
    return items


class RSSProvider:
    def __init__(
        self,
        feeds: list[FeedConfig] | None = None,
        *,
        timeout: float = 8.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.feeds = feeds if feeds is not None else DEFAULT_FEEDS
        self.timeout = timeout
        self.transport = transport

    async def _fetch_one(self, client: httpx.AsyncClient, feed: FeedConfig) -> list[FetchedNews]:
        response = await client.get(feed.url)
        response.raise_for_status()
        if len(response.content) > MAX_FEED_BYTES:
            raise ValueError("feed too large")
        return parse_feed(response.content, feed)

    async def fetch(self) -> list[FetchedNews]:
        async with httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=True,
            transport=self.transport,
            headers={"User-Agent": "MandyNewsBot/1.0 (+rss reader)"},
        ) as client:
            results = await asyncio.gather(
                *(self._fetch_one(client, f) for f in self.feeds), return_exceptions=True
            )
        items: list[FetchedNews] = []
        for feed, result in zip(self.feeds, results, strict=True):
            if isinstance(result, BaseException):
                log.warning("news_feed_failed", feed=feed.url, error=type(result).__name__)
                continue
            items.extend(result)
        return items


class NullProvider:
    async def fetch(self) -> list[FetchedNews]:
        return []
