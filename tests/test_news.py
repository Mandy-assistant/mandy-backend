from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.news.models import NewsCategory, NewsItem
from app.features.news.provider import FeedConfig, FetchedNews, RSSProvider, clean_text, parse_date
from app.features.news.router import get_news_provider

RSS = b"""<?xml version="1.0"?>
<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/"><channel><title>T</title>
<item><title>Gemini 3 &amp; you</title><link>https://ex.com/a</link>
<description>&lt;p&gt;Hello &lt;b&gt;world&lt;/b&gt;&lt;/p&gt;&lt;img src="https://img/x.png"&gt;</description>
<pubDate>Tue, 17 Nov 2026 10:00:00 GMT</pubDate></item>
<item><title>No link</title></item>
<item><title>Media</title><link>https://ex.com/b</link><media:content url="https://img/m.jpg"/></item>
</channel></rss>"""

ATOM = b"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>A</title>
<entry><title>Atom post</title><link rel="alternate" href="https://ex.com/atom"/>
<summary>Short</summary><updated>2026-11-18T08:00:00Z</updated></entry>
</feed>"""


async def _seed_news(db: AsyncSession, n: int = 5) -> list[NewsItem]:
    now = datetime.now(UTC)
    items = [
        NewsItem(
            title=f"Item {i} {'kubernetes' if i == 0 else ''}",
            source="Src",
            url=f"https://news.test/{i}",
            summary="s",
            category=NewsCategory.CLOUD if i % 2 == 0 else NewsCategory.AI,
            published_at=now - timedelta(hours=i),
        )
        for i in range(n)
    ]
    db.add_all(items)
    await db.commit()
    return items


async def test_list_filter_search(auth_client: httpx.AsyncClient, db: AsyncSession) -> None:
    await _seed_news(db)
    r = await auth_client.get("/news", params={"size": 2})
    body = r.json()
    assert body["total"] == 5 and body["pages"] == 3
    assert [i["title"].strip() for i in body["items"]] == ["Item 0 kubernetes", "Item 1"]
    assert body["items"][0]["is_saved"] is False
    r = await auth_client.get("/news", params={"category": "ai"})
    assert r.json()["total"] == 2
    r = await auth_client.get("/news", params={"q": "KUBER"})
    assert r.json()["total"] == 1
    r = await auth_client.get("/news", params={"category": "sports"})
    assert r.status_code == 422


async def test_save_idempotent_and_cache_merge(
    auth_client: httpx.AsyncClient, other_user_client: httpx.AsyncClient, db: AsyncSession
) -> None:
    items = await _seed_news(db)
    target = str(items[1].id)
    await auth_client.get("/news")  # warm the shared cache
    for _ in range(2):
        r = await auth_client.put(f"/news/{target}/save")
        assert r.status_code == 200 and r.json() == {"is_saved": True}
    mine = {i["id"]: i["is_saved"] for i in (await auth_client.get("/news")).json()["items"]}
    theirs = {
        i["id"]: i["is_saved"] for i in (await other_user_client.get("/news")).json()["items"]
    }
    assert mine[target] is True and theirs[target] is False

    saved = (await auth_client.get("/news/saved")).json()
    assert saved["total"] == 1 and saved["items"][0]["is_saved"] is True
    assert (await other_user_client.get("/news/saved")).json()["total"] == 0

    for _ in range(2):
        r = await auth_client.delete(f"/news/{target}/save")
        assert r.status_code == 200 and r.json() == {"is_saved": False}
    assert (await auth_client.get("/news/saved")).json()["total"] == 0
    r = await auth_client.put("/news/00000000-0000-0000-0000-000000000000/save")
    assert r.status_code == 404 and r.json()["error"]["code"] == "NEWS_NOT_FOUND"


class FakeProvider:
    def __init__(self, items: list[FetchedNews]) -> None:
        self.items = items

    async def fetch(self) -> list[FetchedNews]:
        return self.items


async def test_refresh_inserts_new_only(auth_client: httpx.AsyncClient, app, db) -> None:  # type: ignore[no-untyped-def]
    await _seed_news(db, 1)
    await auth_client.get("/news")  # cached with 1 item
    now = datetime.now(UTC)
    fetched = [
        FetchedNews("Dup", "S", "https://news.test/0", "", None, NewsCategory.AI, now),
        FetchedNews("New", "S", "https://news.test/new", "", None, NewsCategory.WEB, now),
        FetchedNews("New", "S", "https://news.test/new", "", None, NewsCategory.WEB, now),
    ]
    app.dependency_overrides[get_news_provider] = lambda: FakeProvider(fetched)
    r = await auth_client.post("/news/refresh")
    assert r.json() == {"added": 1}
    assert (await auth_client.get("/news")).json()["total"] == 2  # cache invalidated
    assert (await auth_client.post("/news/refresh")).json() == {"added": 0}
    app.dependency_overrides[get_news_provider] = lambda: FakeProvider([])
    assert (await auth_client.post("/news/refresh")).json() == {"added": 0}


async def test_default_provider_disabled_in_tests(auth_client: httpx.AsyncClient) -> None:
    r = await auth_client.post("/news/refresh")
    assert r.status_code == 200 and r.json() == {"added": 0}


async def test_rss_provider_parses_and_survives_failures() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/rss":
            return httpx.Response(200, content=RSS)
        if request.url.path == "/atom":
            return httpx.Response(200, content=ATOM)
        if request.url.path == "/broken":
            return httpx.Response(200, content=b"<not xml")
        return httpx.Response(503)

    feeds = [
        FeedConfig("https://feeds.test/rss", "RSS", NewsCategory.AI),
        FeedConfig("https://feeds.test/atom", "Atom", NewsCategory.WEB),
        FeedConfig("https://feeds.test/down", "Down", NewsCategory.DATA),
        FeedConfig("https://feeds.test/broken", "Broken", NewsCategory.DATA),
    ]
    provider = RSSProvider(feeds, transport=httpx.MockTransport(handler))
    items = await provider.fetch()
    by_url = {i.url: i for i in items}
    assert set(by_url) == {"https://ex.com/a", "https://ex.com/b", "https://ex.com/atom"}
    a = by_url["https://ex.com/a"]
    assert a.title == "Gemini 3 & you" and a.summary == "Hello world"
    assert a.image_url == "https://img/x.png" and a.published_at.day == 17
    assert by_url["https://ex.com/b"].image_url == "https://img/m.jpg"
    atom = by_url["https://ex.com/atom"]
    assert atom.category == NewsCategory.WEB and atom.summary == "Short"


def test_text_helpers() -> None:
    assert clean_text("a " * 300, 20).endswith("…")
    assert clean_text(None) == ""
    assert parse_date("garbage") is None
    assert parse_date(None) is None
    assert parse_date("2026-11-18T08:00:00") is not None


@pytest.mark.parametrize("path", ["/news", "/news/saved"])
async def test_news_requires_auth(client: httpx.AsyncClient, path: str) -> None:
    assert (await client.get(path)).status_code == 401
